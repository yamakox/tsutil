import wx
import wx.adv
from pathlib import Path
import os
from subprocess import Popen, PIPE
from .common import *
from .tool_frame import ToolFrame
from .components.video_thumbnail import VideoThumbnail, EVT_VIDEO_RANGE_CHANGED
from ffio import Probe

# MARK: constants

MARGIN = 16
TOOL_NAME = '動画のトリミング'
RAW_SUFFIX = '_RAW'

# MARK: main window

class MainFrame(ToolFrame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=TOOL_NAME, *args, **kw)
        self.enable_save_menu(False)

        frame_sizer = wx.GridSizer(rows=1, cols=1, gap=wx.Size(0, 0))
        panel = wx.Panel(self)
        sizer = wx.FlexGridSizer(rows=0, cols=1, gap=wx.Size(0, 0))
        sizer.AddGrowableCol(0)

        # input file panel
        input_file_panel = wx.Panel(panel)
        input_file_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        input_file_sizer.AddGrowableCol(1)
        input_file_sizer.Add(wx.StaticText(input_file_panel, label='トリミングする動画ファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.input_file_picker = wx.FilePickerCtrl(
            input_file_panel,
            message='動画ファイルを選択してください。',
            wildcard=MOVIE_FILE_WILDCARD,
            style=wx.FLP_OPEN|wx.FLP_USE_TEXTCTRL|wx.FLP_FILE_MUST_EXIST,
        )
        self.input_file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self.__on_input_file_changed)
        input_file_sizer.Add(self.input_file_picker, flag=wx.EXPAND)
        input_file_panel.SetSizerAndFit(input_file_sizer)
        sizer.Add(input_file_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)

        # input video thumbnail 
        sizer.Add(wx.StaticText(panel, label='赤いバーをドラッグして、動画の開始位置と終了位置を指定してください。'), flag=wx.ALIGN_CENTER)
        self.input_video_thumbnail = VideoThumbnail(panel, use_range_bar=True)
        sizer.Add(self.input_video_thumbnail, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        self.preview_video_thumbnail = VideoThumbnail(panel)
        sizer.Add(self.preview_video_thumbnail, flag=wx.EXPAND)

        # trimming button
        trimming_button = wx.Button(panel, label='トリミングした動画ファイルを作成する...')
        trimming_button.Bind(wx.EVT_BUTTON, self.__on_trimming_button_clicked)
        sizer.Add(trimming_button, flag=wx.ALIGN_CENTER|wx.ALL, border=MARGIN)

        # output video thumbnail
        self.output_video_thumbnail = VideoThumbnail(panel)
        sizer.Add(self.output_video_thumbnail, flag=wx.EXPAND)
        sizer.Add(wx.StaticText(panel, label='※ffmpegによるトリミングの結果には多少の誤差が生じます。こちらで目視確認してください。'), flag=wx.ALIGN_CENTER)

        # output file panel
        output_file_panel = wx.Panel(panel)
        output_file_sizer = wx.FlexGridSizer(cols=3, gap=wx.Size(MARGIN, 0))
        output_file_sizer.AddGrowableCol(1)
        output_file_sizer.Add(wx.StaticText(output_file_panel, label='トリミングした動画ファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.output_filename_text = wx.TextCtrl(output_file_panel, value='', style=wx.TE_READONLY)
        output_file_sizer.Add(self.output_filename_text, flag=wx.EXPAND)
        folder_button = wx.Button(output_file_panel, label='フォルダーを開く')
        folder_button.Bind(wx.EVT_BUTTON, self.__on_folder_button_clicked)
        output_file_sizer.Add(folder_button, flag=wx.ALIGN_CENTER_VERTICAL)
        output_file_panel.SetSizerAndFit(output_file_sizer)
        sizer.Add(output_file_panel, flag=wx.EXPAND|wx.TOP, border=MARGIN)

        panel.SetSizer(sizer)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=16)
        self.SetSizerAndFit(frame_sizer)

        self.input_video_thumbnail.Bind(EVT_VIDEO_RANGE_CHANGED, self.__on_video_range_changed)

    def __on_input_file_changed(self, event):
        path = get_path(self.input_file_picker.GetPath())
        if not path_exists(path):
            event.Skip()
            return
        self.input_video_thumbnail.clear()
        self.preview_video_thumbnail.clear()
        self.output_video_thumbnail.clear()
        self.output_filename_text.SetValue('')
        self.input_video_thumbnail.load_video(path)
        event.Skip()

    def __on_video_range_changed(self, event):
        self.preview_video_thumbnail.copy_frames(event.frames[event.start:event.end])
        event.Skip()

    def __on_trimming_button_clicked(self, event):
        if self.input_video_thumbnail.get_frame_count() == 0:
            wx.MessageBox('トリミングする動画が読み込まれていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return

        input_path = get_path(self.input_file_picker.GetPath())
        output_filename = input_path.stem + RAW_SUFFIX + input_path.suffix

        with wx.FileDialog(
            self, 
            'トリミングした動画の保存先ファイル名を入力してください。', 
            defaultDir=str(input_path.parent),
            defaultFile=output_filename,
            wildcard=MOVIE_FILE_WILDCARD,
            style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            output_path = get_path(fileDialog.GetPath())
            self.output_filename_text.SetValue(str(output_path))

            probe = Probe(input_path)
            total_count = self.input_video_thumbnail.get_frame_count()
            start, end = self.input_video_thumbnail.get_frame_range()
            # ss = start / probe.fps
            # to = (end - 1) / probe.fps
            ss = probe.duration * start / total_count
            to = probe.duration * (end - 1) / total_count
            args = ['ffmpeg', '-loglevel', 'error', '-ss', str(ss), '-to', str(to), '-i', str(input_path), '-c', 'copy', '-y', str(output_path)]
            logger.debug(args)
            process = Popen(args, stdout=PIPE, stderr=PIPE, encoding='utf-8')
            stdout_data, stderr_data = process.communicate()
            if process.returncode != 0:
                wx.MessageBox(f'トリミングに失敗しました:\n{stderr_data}', TOOL_NAME, wx.OK|wx.ICON_ERROR)
                event.Skip()
                return
            m_time = input_path.stat().st_mtime
            os.utime(str(output_path), (m_time, m_time))
            self.output_video_thumbnail.load_video(output_path)
        event.Skip()

    def __on_folder_button_clicked(self, event):
        path = get_path(self.output_filename_text.GetValue())
        if not path_exists(path):
            event.Skip()
            return
        wx.LaunchDefaultApplication(str(path.parent))
        event.Skip()
