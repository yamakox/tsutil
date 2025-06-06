import wx
import wx.adv
from pathlib import Path
from subprocess import Popen, PIPE
from .common import *
from .tool_frame import ToolFrame
from .components.video_thumbnail import VideoThumbnail, EVT_VIDEO_LOADED, EVT_VIDEO_POSITION_CHANGED
from .components.image_viewer import ImageViewer
from ffio import Probe
import ffmpeg
import numpy as np
import cv2

# MARK: constants

TOOL_NAME = '動画から画像の展開'

# MARK: main window

class MainFrame(ToolFrame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=TOOL_NAME, *args, **kw)
        self.probe = None

        frame_sizer = wx.GridSizer(rows=1, cols=1, gap=wx.Size(0, 0))
        panel = wx.Panel(self)
        sizer = wx.FlexGridSizer(rows=0, cols=1, gap=wx.Size(0, 0))
        sizer.AddGrowableCol(0)
        row = 0

        # input file panel
        input_file_panel = wx.Panel(panel)
        input_file_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        input_file_sizer.AddGrowableCol(1)
        input_file_sizer.Add(wx.StaticText(input_file_panel, label='画像に展開する動画ファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.input_file_picker = wx.FilePickerCtrl(
            input_file_panel,
            message='動画ファイルを選択してください。',
            wildcard='Movie files (*.mp4;*.mov)|*.mp4;*.mov',
            style=wx.FLP_OPEN|wx.FLP_USE_TEXTCTRL|wx.FLP_FILE_MUST_EXIST,
        )
        self.input_file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self.__on_input_file_changed)
        input_file_sizer.Add(self.input_file_picker, flag=wx.EXPAND)
        input_file_panel.SetSizerAndFit(input_file_sizer)
        sizer.Add(input_file_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # input video thumbnail 
        sizer.Add(wx.StaticText(panel, label='赤い▲をドラッグして、動画のプレビュー位置を指定できます。'), flag=wx.ALIGN_CENTER)
        self.input_video_thumbnail = VideoThumbnail(panel, use_x_arrow=True)
        sizer.Add(self.input_video_thumbnail, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 2

        # preview panel
        preview_panel = wx.Panel(panel)
        preview_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(MARGIN, 0))
        preview_sizer.AddGrowableCol(0)
        preview_sizer.AddGrowableRow(0)
        self.previewer = ImageViewer(preview_panel)
        preview_sizer.Add(self.previewer, flag=wx.EXPAND)
        preview_panel.SetSizerAndFit(preview_sizer)

        sizer.Add(preview_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        sizer.AddGrowableRow(row)
        row += 1



        panel.SetSizer(sizer)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=16)
        self.SetSizerAndFit(frame_sizer)

        self.input_video_thumbnail.Bind(EVT_VIDEO_LOADED, self.__on_video_loaded)
        self.input_video_thumbnail.Bind(EVT_VIDEO_POSITION_CHANGED, self.__on_video_position_changed)

    def __set_previewer(self, position):
        path = Path(self.input_file_picker.GetPath())
        if not path.exists():
            return
        self.SetCursor(wx.Cursor(wx.CURSOR_WAIT))
        try:
            stream = ffmpeg.input(path, ss=position / self.probe.fps).video
            out, err = (
                stream
                .output('pipe:', format='rawvideo', pix_fmt='rgb24', loglevel='error', **{'frames:v': 1})
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            if not len(out):
                wx.MessageBox(f'画像の取り出しに失敗しました:\n{err}', TOOL_NAME, wx.OK|wx.ICON_ERROR)
                return
            w, h = (self.probe.height, self.probe.width) if self.probe.rotation % 180 else (self.probe.width, self.probe.height)
            frame = np.frombuffer(out, np.uint8).reshape(h, w, 3)
            if w > h:
                center = w//2, h//2
                mat = cv2.getRotationMatrix2D(center, 90, 1.0)
                mat[0, 2] += h//2 - center[0]
                mat[1, 2] += w//2 - center[1] - 1
                frame = cv2.warpAffine(frame, mat, (h, w), flags=cv2.INTER_AREA)
            self.previewer.set_image(frame)
        except Exception as e:
            wx.MessageBox(f'画像の取り出しに失敗しました:\n{e}', TOOL_NAME, wx.OK|wx.ICON_ERROR)
        finally:
            self.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))

    def __on_input_file_changed(self, event):
        path = Path(self.input_file_picker.GetPath())
        if not path.exists():
            return
        self.probe = Probe(path)
        self.input_video_thumbnail.clear()
        self.previewer.clear()
        self.input_video_thumbnail.load_video(path)

    def __on_video_loaded(self, event):
        self.__set_previewer(self.input_video_thumbnail.get_frame_position())
        event.Skip()

    def __on_video_position_changed(self, event):
        self.__set_previewer(event.position)
