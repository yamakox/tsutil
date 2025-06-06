import wx
import threading
import numpy as np
import cv2
import time
from pathlib import Path
from ffio import FrameReader, Probe
from .resource import resource

# MARK: constants

RANGE_BAR_WIDTH = 10
PROGRESS_BAR_HEIGHT = 10
ARROW_SIZE = 10
THUMBNAIL_SIZE = (1000, 100)
FRAME_THUMBNAIL_MIN_WIDTH = 10
DRAGGING_NONE = 0
DRAGGING_LEFT = 1
DRAGGING_RIGHT = 2
DRAGGING_RANGE = 3
DRAGGING_X_ARROW = 4

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
    def __init__(self, frames, position):
        super().__init__(myEVT_VIDEO_POSITION_CHANGED)
        self.frames = frames
        self.position = position

# MARK: main class

class VideoThumbnail(wx.Panel):
    def __init__(self, parent, use_range_bar=False, use_x_arrow=False, *args, **kwargs):
        w = THUMBNAIL_SIZE[0] + RANGE_BAR_WIDTH * 2
        h = THUMBNAIL_SIZE[1] + (ARROW_SIZE if use_x_arrow else 0)
        super().__init__(parent, size=parent.FromDIP(wx.Size(w, h)), *args, **kwargs)
        self.use_range_bar = use_range_bar
        self.use_x_arrow = use_x_arrow
        self.start_pos = 0
        self.end_pos = THUMBNAIL_SIZE[0]
        self.x_pos = THUMBNAIL_SIZE[0] // 2
        self.dragging = DRAGGING_NONE
        self.dragging_dx = 0
        self.frames = []
        self.progress_total = 0
        self.progress_current = 0
        self.buf = np.ones((THUMBNAIL_SIZE[1], THUMBNAIL_SIZE[0], 3), dtype=np.uint8) * 192
        self.bitmap = wx.Bitmap.FromBuffer(THUMBNAIL_SIZE[0], THUMBNAIL_SIZE[1], self.buf.tobytes())
        self.bitmap_arrow_up = resource.get_bitmap_arrow_up()

        self.Bind(wx.EVT_PAINT, self.__on_paint)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.__on_destroy)
        if self.use_range_bar or self.use_x_arrow:
            self.Bind(wx.EVT_LEFT_DOWN, self.__on_mouse_down)
            self.Bind(wx.EVT_LEFT_UP, self.__on_mouse_up)
            self.Bind(wx.EVT_MOTION, self.__on_mouse_move)
        self.loading = None

        self.Bind(EVT_VIDEO_LOADING, self.__on_video_loading)
        self.Bind(EVT_VIDEO_LOADED, self.__on_video_loaded)

    def clear(self):
        self.start_pos = 0
        self.end_pos = THUMBNAIL_SIZE[0]
        self.dragging = DRAGGING_NONE
        self.dragging_dx = 0
        self.buf[:] = 192
        self.frames.clear()
        self.progress_total = 0
        self.progress_current = 0
        self.__update_bitmap()

    def load_video(self, path):
        self.ensure_stop_loading()
        self.SetCursor(wx.Cursor(wx.CURSOR_WAIT))
        self.loading = threading.Thread(
            target=self.__video_load_worker, 
            args=(path,), 
            daemon=True,
        )
        self.loading.start()

    def ensure_stop_loading(self):
        if self.loading:
            th = self.loading
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
        if self.loading:
            return 0, 0
        start = len(self.frames) * self.start_pos // THUMBNAIL_SIZE[0]
        end = len(self.frames) * self.end_pos // THUMBNAIL_SIZE[0]
        print(f'{start=} {end=} {len(self.frames)=}')
        return start, end

    def get_frame_position(self):
        if self.loading:
            return 0
        return int((len(self.frames) - 1) * self.x_pos / (THUMBNAIL_SIZE[0] - 1) + .5)

    def __update_bitmap(self):
        self.bitmap.CopyFromBuffer(self.buf.tobytes())
        self.Refresh()

    def __update_thumbnail(self):
        if not self.frames:
            self.buf[:] = 192
            self.__update_bitmap()
            return
        count = len(self.frames)
        thumb_width = THUMBNAIL_SIZE[0] // count
        indices = np.arange(count)
        if thumb_width < FRAME_THUMBNAIL_MIN_WIDTH:
            thumb_width = FRAME_THUMBNAIL_MIN_WIDTH
            count = THUMBNAIL_SIZE[0] // thumb_width
            indices = (np.linspace(0, len(self.frames) - 1, count) + .5).astype(int)
        dw = thumb_width - self.frames[0].shape[1]
        if dw > 0:
            fx, fw = 0, self.frames[0].shape[1]
            self.buf[:] = 192
        else:
            dwh = -dw // 2
            fx, fw = dwh, thumb_width
        x = 0
        for i in indices:
            self.buf[:, x:x + fw, :] = self.frames[i][:, fx:fx + fw, :]
            x += thumb_width
        self.__update_bitmap()

    def __on_paint(self, event):
        dc = wx.PaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            gc.DrawBitmap(self.bitmap, RANGE_BAR_WIDTH, 0, *THUMBNAIL_SIZE)

            if self.progress_total > 0:
                gc.SetBrush(wx.Brush(wx.Colour(64, 64, 64, 255)))
                gc.DrawRectangle(RANGE_BAR_WIDTH, THUMBNAIL_SIZE[1] - PROGRESS_BAR_HEIGHT, 
                                 THUMBNAIL_SIZE[0], PROGRESS_BAR_HEIGHT)
                gc.SetBrush(wx.Brush(wx.Colour(0, 255, 64, 255)))
                gc.DrawRectangle(RANGE_BAR_WIDTH + 1, THUMBNAIL_SIZE[1] - PROGRESS_BAR_HEIGHT + 1, 
                                 min(self.progress_current * THUMBNAIL_SIZE[0] // self.progress_total, THUMBNAIL_SIZE[0] - 2), PROGRESS_BAR_HEIGHT - 2)

            # これ以降は動画読込中には表示しないもの(マウス操作の対象物)を描画する
            if self.loading:
                return

            if self.use_range_bar:
                gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 128)))
                if RANGE_BAR_WIDTH < self.start_pos:
                    gc.DrawRectangle(RANGE_BAR_WIDTH, 0, self.start_pos, THUMBNAIL_SIZE[1])
                if self.end_pos + RANGE_BAR_WIDTH < THUMBNAIL_SIZE[0]:
                    gc.DrawRectangle(RANGE_BAR_WIDTH + self.end_pos + RANGE_BAR_WIDTH, 0, THUMBNAIL_SIZE[0] - (self.end_pos + RANGE_BAR_WIDTH), THUMBNAIL_SIZE[1])
                
                gc.SetBrush(wx.Brush(wx.Colour(255, 0, 0, 192)))
                gc.DrawRectangle(self.start_pos, 0, RANGE_BAR_WIDTH, THUMBNAIL_SIZE[1])
                gc.DrawRectangle(RANGE_BAR_WIDTH + self.end_pos, 0, RANGE_BAR_WIDTH, THUMBNAIL_SIZE[1])

            if self.use_x_arrow:
                gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 10)))
                gc.DrawRectangle(RANGE_BAR_WIDTH, THUMBNAIL_SIZE[1], THUMBNAIL_SIZE[0], ARROW_SIZE)
                gc.DrawBitmap(self.bitmap_arrow_up, RANGE_BAR_WIDTH + self.x_pos - ARROW_SIZE // 2, THUMBNAIL_SIZE[1], ARROW_SIZE, ARROW_SIZE)

    def __on_mouse_down(self, event):
        if self.loading:
            return
        x = event.GetX()
        y = event.GetY()
        if self.use_range_bar and y < THUMBNAIL_SIZE[1]:
            if x < self.start_pos + RANGE_BAR_WIDTH:
                self.dragging = DRAGGING_LEFT
                self.dragging_dx = x - (self.start_pos + RANGE_BAR_WIDTH)
            elif self.end_pos + RANGE_BAR_WIDTH < x:
                self.dragging = DRAGGING_RIGHT
                self.dragging_dx = x - (self.end_pos + RANGE_BAR_WIDTH)
            else:
                self.dragging = DRAGGING_RANGE
                self.dragging_dx = x - (self.start_pos + RANGE_BAR_WIDTH)
        elif self.use_x_arrow and y >= THUMBNAIL_SIZE[1]:
            if RANGE_BAR_WIDTH <= x < THUMBNAIL_SIZE[0] + RANGE_BAR_WIDTH:
                self.dragging = DRAGGING_X_ARROW
                self.x_pos = max(0, min(x - RANGE_BAR_WIDTH, THUMBNAIL_SIZE[0] - 1))
                self.__update_bitmap()

    def __on_mouse_up(self, event):
        if self.loading:
            return
        if self.frames:
            if self.dragging in [DRAGGING_LEFT, DRAGGING_RIGHT, DRAGGING_RANGE]:
                wx.QueueEvent(self, VideoRangeChangedEvent(self.frames, *self.get_frame_range()))
            elif self.dragging == DRAGGING_X_ARROW:
                wx.QueueEvent(self, VideoPositionChangedEvent(self.frames, self.get_frame_position()))
        self.dragging = DRAGGING_NONE
        self.dragging_dx = 0

    def __on_mouse_move(self, event):
        if self.loading or not event.Dragging() or not event.LeftIsDown():
            return
        x = event.GetX()
        if self.dragging == DRAGGING_LEFT:
            self.start_pos = max(0, min(x - self.dragging_dx - RANGE_BAR_WIDTH, self.end_pos))
            self.__update_bitmap()
        elif self.dragging == DRAGGING_RIGHT:
            self.end_pos = min(THUMBNAIL_SIZE[0], max(x - self.dragging_dx - RANGE_BAR_WIDTH, self.start_pos))
            self.__update_bitmap()
        elif self.dragging == DRAGGING_RANGE:
            w = self.end_pos - self.start_pos
            self.start_pos = max(0, min(x - self.dragging_dx - RANGE_BAR_WIDTH, THUMBNAIL_SIZE[0] - w))
            self.end_pos = self.start_pos + w
            self.__update_bitmap()
        elif self.dragging == DRAGGING_X_ARROW:
            self.x_pos = max(0, min(x - RANGE_BAR_WIDTH, THUMBNAIL_SIZE[0] - 1))
            self.__update_bitmap()

    def __on_destroy(self, event):
        self.ensure_stop_loading()
        event.Skip()

    def __on_video_loading(self, event):
        self.__update_thumbnail()

    def __on_video_loaded(self, event):
        if self.loading:
            # 次の動画の読み込みが既に開始されている
            return
        self.__update_thumbnail()
        wx.QueueEvent(self, VideoRangeChangedEvent(self.frames, *self.get_frame_range()))
        self.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))

    def __video_load_worker(self, path):
        try:
            self.frames.clear()
            probe = Probe(path)
            self.progress_total = probe.n_frames
            self.progress_current = 0
            self.__update_thumbnail()
            with FrameReader(path) as reader:
                prev_time = time.time()
                for i, frame in enumerate(reader.frames()):
                    if not self.loading:
                        break
                    self.progress_current = i + 1
                    h, w, _ = frame.shape
                    self.frames.append(cv2.resize(frame, ((w * THUMBNAIL_SIZE[1]) // h, THUMBNAIL_SIZE[1]), interpolation=cv2.INTER_LANCZOS4))
                    now = time.time()
                    if now - prev_time >= 0.25:
                        prev_time = now
                        wx.QueueEvent(self, VideoLoadingEvent())
                else:
                    wx.QueueEvent(self, VideoLoadingEvent())
                    time.sleep(0.25)
                    self.loading = None
                    self.progress_total = 0
                    self.progress_current = 0
                    wx.QueueEvent(self, VideoLoadedEvent())
        except Exception as e:
            print(e)
