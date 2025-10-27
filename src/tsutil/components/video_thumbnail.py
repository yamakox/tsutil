import wx
import threading
import numpy as np
import cv2
import time
from pathlib import Path
import os
from types import SimpleNamespace
import concurrent.futures as futures
from numba import njit
from fffio import FrameReader, Probe
from .resource import resource
from ..common import *
from .histogram_view import HistogramView
from ..functions import DeshakingCorrection

# MARK: constants

RANGE_BAR_WIDTH = 10
PROGRESS_BAR_HEIGHT = 10
ARROW_SIZE = 12
THUMBNAIL_SIZE = (1000, 100)
FRAME_THUMBNAIL_MIN_WIDTH = 10
DRAGGING_NONE = 0
DRAGGING_LEFT = 1
DRAGGING_RIGHT = 2
DRAGGING_RANGE = 3
DRAGGING_X_ARROW = 4
DRAGGING_LEFT_ARROW = 5
DRAGGING_RIGHT_ARROW = 6

MAX_WORKERS = 8
MAX_WORKERS2 = 16

# MARK: events

myEVT_VIDEO_LOADING = wx.NewEventType()
EVT_VIDEO_LOADING = wx.PyEventBinder(myEVT_VIDEO_LOADING)

class VideoLoadingEvent(wx.ThreadEvent):
    def __init__(self):
        super().__init__(myEVT_VIDEO_LOADING)

myEVT_VIDEO_LOADED = wx.NewEventType()
EVT_VIDEO_LOADED = wx.PyEventBinder(myEVT_VIDEO_LOADED)

class VideoLoadedEvent(wx.ThreadEvent):
    def __init__(self):
        super().__init__(myEVT_VIDEO_LOADED)

myEVT_VIDEO_LOAD_ERROR = wx.NewEventType()
EVT_VIDEO_LOAD_ERROR = wx.PyEventBinder(myEVT_VIDEO_LOAD_ERROR)

class VideoLoadErrorEvent(wx.ThreadEvent):
    def __init__(self, message):
        super().__init__(myEVT_VIDEO_LOAD_ERROR)
        self.message = message

myEVT_VIDEO_RANGE_CHANGED = wx.NewEventType()
EVT_VIDEO_RANGE_CHANGED = wx.PyEventBinder(myEVT_VIDEO_RANGE_CHANGED)

class VideoRangeChangedEvent(wx.ThreadEvent):
    def __init__(self, frames, start, end):
        super().__init__(myEVT_VIDEO_RANGE_CHANGED)
        self.frames = frames
        self.start = start
        self.end = end

myEVT_VIDEO_POSITION_CHANGED = wx.NewEventType()
EVT_VIDEO_POSITION_CHANGED = wx.PyEventBinder(myEVT_VIDEO_POSITION_CHANGED)

class VideoPositionChangedEvent(wx.ThreadEvent):
    def __init__(self, frames, position, frame_count):
        super().__init__(myEVT_VIDEO_POSITION_CHANGED)
        self.frames = frames
        self.position = position
        self.frame_count = frame_count

# MARK: subroutines

@njit
def _update_thumbnail(buf, frames, indices, x):
    for i, index in enumerate(indices):
        frame = frames[index]
        fw = x[i + 1] - x[i]
        if frame.shape[1] <= fw:
            buf[:, x[i]:x[i] + frame.shape[1], :] = frame
        else:
            dwh = (frame.shape[1] - fw) // 2
            buf[:, x[i]:x[i + 1], :] = frame[:, dwh:dwh + fw, :]

# MARK: main class

class VideoThumbnail(wx.Panel):
    def __init__(self, parent, use_range_bar=False, use_x_arrow=False, *args, **kwargs):
        self.RANGE_BAR_WIDTH = dpi_aware(parent, RANGE_BAR_WIDTH)
        self.PROGRESS_BAR_HEIGHT = dpi_aware(parent, PROGRESS_BAR_HEIGHT)
        self.ARROW_SIZE = dpi_aware(parent, ARROW_SIZE)
        self.thumbnail_size = (dpi_aware(parent, THUMBNAIL_SIZE[0]), dpi_aware(parent, THUMBNAIL_SIZE[1]))
        self.frame_thumbnail_min_width = dpi_aware(parent, FRAME_THUMBNAIL_MIN_WIDTH)

        self.client_width = self.thumbnail_size[0] + self.RANGE_BAR_WIDTH * 2
        self.client_height = self.thumbnail_size[1] + (self.ARROW_SIZE if use_x_arrow else 0)
        super().__init__(parent, *args, **kwargs)
        self.SetSizeHints(
            self.client_width,
            self.client_height,
            -1,
            self.client_height,
        )
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.use_range_bar = use_range_bar
        self.use_x_arrow = use_x_arrow
        self.histogram_view = None
        self.start_pos = 0.0
        self.end_pos = 1.0
        self.frame_pos = None
        self.dragging = DRAGGING_NONE
        self.dragging_dx = 0
        self.frames = []
        self.image_catalog = []
        self.progress_total = 0
        self.progress_current = 0
        self.buf = np.ones((self.thumbnail_size[1], self.thumbnail_size[0], 3), dtype=np.uint8) * 192
        self.bitmap = wx.Bitmap.FromBuffer(self.buf.shape[1], self.buf.shape[0], self.buf.tobytes())
        self.bitmap_arrow_up = resource.get_bitmap_arrow_up()
        self.bitmap_arrow_left = resource.get_bitmap_arrow_left()
        self.bitmap_arrow_right = resource.get_bitmap_arrow_right()

        self.Bind(wx.EVT_PAINT, self.__on_paint)
        self.Bind(wx.EVT_SIZE, self.__on_size)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.__on_destroy)
        if self.use_range_bar or self.use_x_arrow:
            self.Bind(wx.EVT_LEFT_DOWN, self.__on_mouse_down)
            self.Bind(wx.EVT_LEFT_UP, self.__on_mouse_up)
            self.Bind(wx.EVT_MOTION, self.__on_mouse_move)
        self.loading = None

        self.Bind(EVT_VIDEO_LOADING, self.__on_video_loading)
        self.Bind(EVT_VIDEO_LOADED, self.__on_video_loaded)
        self.Bind(EVT_VIDEO_LOAD_ERROR, self.__on_load_error)

    def set_histogram_view(self, histogram_view):
        self.histogram_view = histogram_view

    def clear(self):
        self.start_pos = 0.0
        self.end_pos = 1.0
        self.dragging = DRAGGING_NONE
        self.dragging_dx = 0
        self.buf[:] = 192
        self.frames.clear()
        self.image_catalog.clear()
        self.progress_total = 0
        self.progress_current = 0
        self.__update_bitmap()

    def load_video(self, path: Path, rotation=0, filter_complex=None, output_path: Path=None, format='PNG'):
        self.ensure_stop_loading()
        self.SetCursor(wx.Cursor(wx.CURSOR_WAIT))
        self.loading = threading.Thread(
            target=self.__video_load_worker, 
            args=(path, rotation, filter_complex, output_path, format), 
            daemon=True,
        )
        self.loading.start()

    def load_image_catalog(self, path: Path, correction_model: CorrectionDataModel=None, output_path: Path=None):
        self.ensure_stop_loading()
        self.SetCursor(wx.Cursor(wx.CURSOR_WAIT))
        self.loading = threading.Thread( 
            target=self.__image_catalog_load_worker, 
            args=(path, correction_model, output_path), 
            daemon=True, 
        )
        self.loading.start()

    def ensure_stop_loading(self):
        th = self.loading
        if th:
            self.loading = None
            th.join()
        self.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))
        self.clear()

    def copy_frames(self, frames):
        self.frames.clear()
        self.frames.extend(frames)
        wx.QueueEvent(self, VideoLoadingEvent())

    def get_frame_count(self):
        return 0 if self.loading else len(self.frames)

    def get_frame_range(self):
        if self.loading or not self.frames:
            return 0, 0
        start = int(len(self.frames) * self.start_pos + .5)
        end = int(len(self.frames) * self.end_pos + .5)
        logger.debug(f'{start=} {end=} {len(self.frames)=}')
        return start, end

    def get_frame_position(self):
        return self.frame_pos

    def set_frame_position(self, frame_pos):
        if self.loading or not self.frames:
            return
        self.frame_pos = frame_pos
        self.Refresh()

    def get_image_catalog(self):
        if self.loading:
            return []
        return self.image_catalog

    def set_progress(self, progress_total, progress_count):
        self.progress_total = progress_total
        self.progress_current = progress_count
        self.Refresh()

    def __get_start_pos_x(self):
        return int(self.start_pos * self.thumbnail_size[0] + .5)
    
    def __get_end_pos_x(self):
        return int(self.end_pos * self.thumbnail_size[0] + .5)

    def __update_bitmap(self):
        self.bitmap.CopyFromBuffer(self.buf.tobytes())
        self.Refresh()

    def __update_thumbnail(self):
        self.buf[:] = 192
        if not self.frames:
            self.__update_bitmap()
            return
        count = len(self.frames)
        indices = np.arange(count)
        thumb_width = self.buf.shape[1] // count
        if thumb_width < self.frame_thumbnail_min_width:
            thumb_width = self.frame_thumbnail_min_width
            count = self.buf.shape[1] // thumb_width
            indices = (np.linspace(0, len(self.frames) - 1, count) + .5).astype(int)
        x = (np.linspace(0, self.buf.shape[1], count + 1) + .5).astype(int)
        _update_thumbnail(self.buf, self.frames, indices, x)  # numbaで高速化
        self.__update_bitmap()

    def __on_size(self, event):
        size = self.GetSize()
        self.client_width = size.GetWidth()
        self.client_height = size.GetHeight()
        self.thumbnail_size = (
            (self.client_width - self.RANGE_BAR_WIDTH * 2), 
            self.client_height - (self.ARROW_SIZE if self.use_x_arrow else 0)
        )
        self.buf = np.ones((self.thumbnail_size[1], self.thumbnail_size[0], 3), dtype=np.uint8) * 192
        self.bitmap = wx.Bitmap.FromBuffer(self.buf.shape[1], self.buf.shape[0], self.buf.tobytes())
        self.__update_thumbnail()
        event.Skip()

    def __on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            gc.SetInterpolationQuality(wx.INTERPOLATION_NONE)
            gc.DrawBitmap(self.bitmap, self.RANGE_BAR_WIDTH, 0, *self.thumbnail_size)
            gc.SetInterpolationQuality(wx.INTERPOLATION_DEFAULT)

            if self.progress_total > 0:
                gc.SetBrush(wx.Brush(wx.Colour(64, 64, 64, 255)))
                gc.DrawRectangle(self.RANGE_BAR_WIDTH, self.thumbnail_size[1] - self.PROGRESS_BAR_HEIGHT, 
                                 self.thumbnail_size[0], self.PROGRESS_BAR_HEIGHT)
                gc.SetBrush(wx.Brush(wx.Colour(0, 255, 64, 255)))
                gc.DrawRectangle(self.RANGE_BAR_WIDTH + 1, self.thumbnail_size[1] - self.PROGRESS_BAR_HEIGHT + 1, 
                                 min(self.progress_current * self.thumbnail_size[0] // self.progress_total, self.thumbnail_size[0] - 2), self.PROGRESS_BAR_HEIGHT - 2)

            # これ以降は動画読込中には表示しないもの(マウス操作の対象物)を描画する
            if self.loading:
                return

            if self.use_range_bar:
                gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 128)))
                if self.RANGE_BAR_WIDTH < self.__get_start_pos_x():
                    gc.DrawRectangle(self.RANGE_BAR_WIDTH, 0, self.__get_start_pos_x(), self.thumbnail_size[1])
                if self.__get_end_pos_x() + self.RANGE_BAR_WIDTH < self.thumbnail_size[0]:
                    gc.DrawRectangle(self.RANGE_BAR_WIDTH + self.__get_end_pos_x() + self.RANGE_BAR_WIDTH, 0, self.thumbnail_size[0] - (self.__get_end_pos_x() + self.RANGE_BAR_WIDTH), self.thumbnail_size[1])
                
                gc.SetBrush(wx.Brush(wx.Colour(255, 0, 0, 192)))
                gc.DrawRectangle(self.__get_start_pos_x(), 0, self.RANGE_BAR_WIDTH, self.thumbnail_size[1])
                gc.DrawRectangle(self.RANGE_BAR_WIDTH + self.__get_end_pos_x(), 0, self.RANGE_BAR_WIDTH, self.thumbnail_size[1])

            if self.use_x_arrow:
                gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 10)))
                gc.DrawRectangle(self.RANGE_BAR_WIDTH, self.thumbnail_size[1], self.thumbnail_size[0], self.ARROW_SIZE)
                if len(self.frames) > 0 and self.frame_pos is not None:
                    x = self.RANGE_BAR_WIDTH + int(self.frame_pos * (self.thumbnail_size[0] - 1) / (len(self.frames) - 1) + .5) - self.ARROW_SIZE // 2
                else:
                    x = self.RANGE_BAR_WIDTH + self.thumbnail_size[0] // 2 - self.ARROW_SIZE // 2
                gc.DrawBitmap(self.bitmap_arrow_up, x, self.thumbnail_size[1], self.ARROW_SIZE, self.ARROW_SIZE)
                gc.DrawBitmap(self.bitmap_arrow_left, self.RANGE_BAR_WIDTH - self.ARROW_SIZE, self.thumbnail_size[1], self.ARROW_SIZE, self.ARROW_SIZE)
                gc.DrawBitmap(self.bitmap_arrow_right, self.RANGE_BAR_WIDTH + self.thumbnail_size[0], self.thumbnail_size[1], self.ARROW_SIZE, self.ARROW_SIZE)

    def __on_mouse_down(self, event):
        if self.loading:
            return
        x = event.GetX()
        y = event.GetY()
        if self.use_range_bar and y < self.thumbnail_size[1]:
            if x < self.__get_start_pos_x() + self.RANGE_BAR_WIDTH:
                capture_mouse(self)
                self.dragging = DRAGGING_LEFT
                self.dragging_dx = x - (self.__get_start_pos_x() + self.RANGE_BAR_WIDTH)
            elif self.__get_end_pos_x() + self.RANGE_BAR_WIDTH < x < self.thumbnail_size[0] + self.RANGE_BAR_WIDTH * 2:
                capture_mouse(self)
                self.dragging = DRAGGING_RIGHT
                self.dragging_dx = x - (self.__get_end_pos_x() + self.RANGE_BAR_WIDTH)
            else:
                capture_mouse(self)
                self.dragging = DRAGGING_RANGE
                self.dragging_dx = x - (self.__get_start_pos_x() + self.RANGE_BAR_WIDTH)
        elif self.use_x_arrow and y >= self.thumbnail_size[1] and len(self.frames) > 0:
            if x < self.RANGE_BAR_WIDTH:
                capture_mouse(self)
                self.dragging = DRAGGING_LEFT_ARROW
            elif x < self.thumbnail_size[0] + self.RANGE_BAR_WIDTH:
                capture_mouse(self)
                self.dragging = DRAGGING_X_ARROW
                self.frame_pos = max(0, min(int((len(self.frames) - 1) * (x - self.RANGE_BAR_WIDTH) / (self.thumbnail_size[0] - 1) + .5), len(self.frames) - 1))
                self.__update_bitmap()
            elif x < self.thumbnail_size[0] + self.RANGE_BAR_WIDTH * 2:
                capture_mouse(self)
                self.dragging = DRAGGING_RIGHT_ARROW
        event.Skip()

    def __on_mouse_up(self, event):
        if self.loading:
            return
        if self.frames:
            if self.dragging in [DRAGGING_LEFT, DRAGGING_RIGHT, DRAGGING_RANGE]:
                wx.QueueEvent(self, VideoRangeChangedEvent(self.frames, *self.get_frame_range()))
            elif self.dragging == DRAGGING_X_ARROW:
                wx.QueueEvent(self, VideoPositionChangedEvent(self.frames, self.get_frame_position(), len(self.frames)))
            elif self.dragging == DRAGGING_LEFT_ARROW:
                self.frame_pos = max(0, self.frame_pos - 1)
                self.__update_bitmap()
                wx.QueueEvent(self, VideoPositionChangedEvent(self.frames, self.get_frame_position(), len(self.frames)))
            elif self.dragging == DRAGGING_RIGHT_ARROW:
                self.frame_pos = min(self.frame_pos + 1, len(self.frames) - 1)
                self.__update_bitmap()
                wx.QueueEvent(self, VideoPositionChangedEvent(self.frames, self.get_frame_position(), len(self.frames)))
        release_mouse(self)
        self.dragging = DRAGGING_NONE
        self.dragging_dx = 0
        event.Skip()

    def __on_mouse_move(self, event):
        if self.loading or not event.Dragging() or not event.LeftIsDown():
            return
        x = min(max(0, event.GetX()), self.client_width - 1)
        if self.dragging == DRAGGING_LEFT:
            self.start_pos = max(0, min(x - self.dragging_dx - self.RANGE_BAR_WIDTH, self.__get_end_pos_x())) / self.thumbnail_size[0]
            self.__update_bitmap()
        elif self.dragging == DRAGGING_RIGHT:
            self.end_pos = min(self.thumbnail_size[0], max(x - self.dragging_dx - self.RANGE_BAR_WIDTH, self.__get_start_pos_x())) / self.thumbnail_size[0]
            self.__update_bitmap()
        elif self.dragging == DRAGGING_RANGE:
            _w = self.end_pos - self.start_pos
            w = _w * self.thumbnail_size[0]
            self.start_pos = max(0, min(x - self.dragging_dx - self.RANGE_BAR_WIDTH, self.thumbnail_size[0] - w)) / self.thumbnail_size[0]
            self.end_pos = self.start_pos + _w
            self.__update_bitmap()
        elif self.dragging == DRAGGING_X_ARROW:
            if len(self.frames) > 0:
                self.frame_pos = max(0, min(int((len(self.frames) - 1) * (x - self.RANGE_BAR_WIDTH) / (self.thumbnail_size[0] - 1) + .5), len(self.frames) - 1))
            self.__update_bitmap()
        event.Skip()

    def __on_destroy(self, event):
        self.ensure_stop_loading()
        event.Skip()

    def __on_video_loading(self, event):
        self.__update_thumbnail()
        event.Skip()

    def __on_video_loaded(self, event):
        if self.loading:
            # 次の動画の読み込みが既に開始されている
            return
        self.__update_thumbnail()
        wx.QueueEvent(self, VideoRangeChangedEvent(self.frames, *self.get_frame_range()))
        self.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))
        self.Refresh()
        event.Skip()

    def __on_load_error(self, event):
        wx.MessageBox(event.message, APP_NAME, wx.OK|wx.ICON_ERROR)
        self.ensure_stop_loading()
        event.Skip()

    def __video_load_worker(self, path, rotation=0, filter_complex=None, output_path=None, format='PNG'):
        output_fd = None
        try:
            self.frames.clear()
            probe = Probe(path)
            self.progress_total = probe.n_frames
            self.progress_current = 0
            wx.QueueEvent(self, VideoLoadingEvent())
            if output_path:
                output_fd = open(output_path, 'w')
                output_parent_path = output_path.parent
                output_dir = Path(output_path.stem)
                os.makedirs(output_parent_path / output_dir, exist_ok=True)
                if format == 'TIFF':
                    pix_fmt = 'rgb48'
                    image_file_ext = '.tif'
                else:
                    pix_fmt = 'rgb24'
                    image_file_ext = '.png'
            else:
                pix_fmt = 'rgb24'
            future_list = []
            def _save_frame(filename, frame):
                cv2.imwrite(filename, frame)
            with futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                with FrameReader(path, filter_complex=filter_complex, pix_fmt=pix_fmt) as reader:
                    prev_time = time.time()
                    if self.histogram_view:
                        self.histogram_view.begin_histogram()
                    for i, frame in enumerate(reader.frames()):
                        if not self.loading:
                            break
                        self.progress_current = i + 1
                        if rotation == 90:
                            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                        elif rotation == 180:
                            frame = cv2.rotate(frame, cv2.ROTATE_180)
                        elif rotation == 270:
                            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                        h, w, _ = frame.shape
                        if output_path:
                            image_filename = output_dir / f'f{i + 1:05d}{image_file_ext}'
                            future = executor.submit(_save_frame, output_parent_path / image_filename, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                            future_list.append(future)
                            if len(future_list) >= MAX_WORKERS:
                                done, not_done = futures.wait(future_list, return_when=futures.FIRST_COMPLETED)
                                future_list = list(not_done)
                            output_fd.write(f'{str(image_filename)}\n')
                        frame = cv2.resize(frame, ((w * self.thumbnail_size[1]) // h, self.thumbnail_size[1]), interpolation=cv2.INTER_LINEAR_EXACT)
                        if frame.dtype == np.uint16:
                            frame = (frame // 256).astype(np.uint8)
                        self.frames.append(frame)
                        if self.histogram_view:
                            self.histogram_view.add_histogram(frame)
                        now = time.time()
                        if now - prev_time >= 0.25:
                            prev_time += 0.25
                            wx.QueueEvent(self, VideoLoadingEvent())
                    else:
                        done, not_done = futures.wait(future_list, return_when=futures.ALL_COMPLETED)
                        failures = [future for future in not_done if not future.result()]
                        if failures:
                            wx.QueueEvent(self, VideoLoadErrorEvent('連続画像ファイルの保存に失敗したファイルがあります。'))
                        wx.QueueEvent(self, VideoLoadingEvent())
                        time.sleep(0.25)
                        self.loading = None
                        if self.frame_pos is None:
                            self.frame_pos = len(self.frames) // 2
                        else:
                            self.frame_pos = max(0, min(self.frame_pos, len(self.frames) - 1))
                        self.progress_total = 0
                        self.progress_current = 0
                        if self.histogram_view:
                            self.histogram_view.end_histogram()
                        wx.QueueEvent(self, VideoLoadedEvent())
        except Exception as e:
            if output_fd:
                output_fd.close()
            wx.QueueEvent(self, VideoLoadErrorEvent(str(e)))
        finally:
            self.loading = None

    def __image_catalog_load_worker(self, path, correction_model, output_path):
        output = None
        try:
            self.frames.clear()
            parent_path = path.parent
            with open(path, 'r') as reader:
                self.image_catalog = [parent_path / line.rstrip() for line in reader]
            self.progress_total = len(self.image_catalog)
            self.progress_current = 0
            wx.QueueEvent(self, VideoLoadingEvent())
            if output_path:
                output = SimpleNamespace(**dict(
                    fd = open(output_path, 'w'), 
                    indexed_filenames = {}, 
                    parent_path = output_path.parent, 
                    dir_name = Path(output_path.stem), 
                    log_fd = open(os.devnull, 'w')  # open(output_path.with_suffix('.log'), 'w'), 
                ))
                os.makedirs(output.parent_path / output.dir_name, exist_ok=True)
            if correction_model is None:
                base_frame = None
            else:
                base_frame = cv2.cvtColor(cv2.imread(str(self.image_catalog[correction_model.base_frame_pos]), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB)
            future_list = []
            indexed_frame = {}
            def _load_and_save_frame(lock, indexed_frame, index, image_path, output, correction_model, base_frame):
                if not image_path.exists():
                    logger.error(f'File not found: {image_path}')
                    return
                frame = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
                if output:
                    image_filename = output.dir_name / image_path.name
                    if correction_model is not None:
                        deshaking_correction = DeshakingCorrection()
                        deshaking_correction.set_base_image(base_frame)
                        deshaking_correction.set_sample_image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), index)
                        fields = correction_model.shaking_detection_fields if correction_model.use_deshake_correction else []
                        angle = correction_model.rotation_angle if correction_model.use_rotation_correction else 0.0
                        mat = deshaking_correction.compute(fields, angle, output.log_fd)
                        if correction_model.use_perspective_correction:
                            mat = correction_model.perspective_points.get_transform_matrix() @ mat
                        frame = cv2.warpPerspective(frame, mat, (frame.shape[1], frame.shape[0]), flags=cv2.INTER_AREA)
                    if not correction_model.clip.is_none():
                        frame = frame[correction_model.clip.top:correction_model.clip.bottom, correction_model.clip.left:correction_model.clip.right, :]
                    cv2.imwrite(output.parent_path / image_filename, frame)
                    output.indexed_filenames[index] = str(image_filename)
                h, w, _ = frame.shape
                frame = cv2.cvtColor(cv2.resize(frame, ((w * self.thumbnail_size[1]) // h, self.thumbnail_size[1]), interpolation=cv2.INTER_LINEAR_EXACT), cv2.COLOR_BGR2RGB)
                if frame.dtype == np.uint16:
                    frame = (frame / 256).astype(np.uint8)
                with lock:
                    indexed_frame[index] = frame
                    if self.histogram_view:
                        self.histogram_view.add_histogram(frame)
            with futures.ThreadPoolExecutor(max_workers=MAX_WORKERS2) as executor:
                lock = threading.Lock()
                prev_time = time.time()
                if self.histogram_view:
                    self.histogram_view.begin_histogram()
                for i, image_path in enumerate(self.image_catalog):
                    if not self.loading:
                        break
                    self.progress_current = i + 1
                    future = executor.submit(_load_and_save_frame, lock, indexed_frame, i, image_path, output, correction_model, base_frame)
                    future_list.append(future)
                    if len(future_list) >= MAX_WORKERS2:
                        done, not_done = futures.wait(future_list, return_when=futures.FIRST_COMPLETED)
                        future_list = list(not_done)
                    now = time.time()
                    if now - prev_time >= 0.25:
                        prev_time += 0.25
                        self.frames = [indexed_frame[i] for i in sorted(indexed_frame.keys())]
                        wx.QueueEvent(self, VideoLoadingEvent())
                else:
                    done, not_done = futures.wait(future_list, return_when=futures.ALL_COMPLETED)
                    failures = [future for future in not_done if not future.result()]
                    if output:
                        for i in sorted(output.indexed_filenames.keys()):
                            output.fd.write(output.indexed_filenames[i] + '\n')
                    if failures:
                        wx.QueueEvent(self, VideoLoadErrorEvent('連続画像ファイルの入出力処理に失敗したファイルがあります。'))
                    self.frames = [indexed_frame[i] for i in sorted(indexed_frame.keys())]
                    wx.QueueEvent(self, VideoLoadingEvent())
                    time.sleep(0.25)
                    self.loading = None
                    if self.frame_pos is None or self.frame_pos > len(self.frames) - 1:
                        self.frame_pos = len(self.frames) // 2
                    else:
                        self.frame_pos = max(0, min(self.frame_pos, len(self.frames) - 1))
                    self.progress_total = 0
                    self.progress_current = 0
                    if self.histogram_view:
                        self.histogram_view.end_histogram()
                    wx.QueueEvent(self, VideoLoadedEvent())
        except Exception as e:
            if output:
                output.fd.close()
                output.log_fd.close()
            wx.QueueEvent(self, VideoLoadErrorEvent(str(e)))
        finally:
            self.loading = None
