import wx
import wx.adv
from pathlib import Path
import time
from .common import *
from .tool_frame import ToolFrame
from .components.video_thumbnail import VideoThumbnail, EVT_VIDEO_LOADED, EVT_VIDEO_POSITION_CHANGED
from .components.image_viewer import ImageViewer, EVT_MOUSE_OVER_IMAGE
from .components.histogram_view import HistogramView
from ffio import Probe
import ffmpeg
import numpy as np
import cv2
import json
import re

# MARK: constants

MARGIN = 10
TOOL_NAME = '動画から連続画像の展開'
SETTING_EXTENSION = '.tsuextract.json'
RAW_SUFFIX = '_RAW'

# MARK: main window

class MainFrame(ToolFrame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=TOOL_NAME, *args, **kw)
        self.probe = None
        self.frame = None
        self.rotation = 0

        frame_sizer = wx.GridSizer(rows=1, cols=1, gap=wx.Size(0, 0))
        panel = wx.Panel(self)
        sizer = wx.FlexGridSizer(rows=0, cols=1, gap=wx.Size(0, 0))
        sizer.AddGrowableCol(0)
        row = 0

        # input file panel
        input_file_panel = wx.Panel(panel)
        input_file_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        input_file_sizer.AddGrowableCol(1)
        input_file_sizer.Add(wx.StaticText(input_file_panel, label='連続画像に展開する動画ファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.input_file_picker = wx.FilePickerCtrl(
            input_file_panel,
            message='動画ファイルを選択してください。', 
            wildcard=INPUT_MOVIE_FILE_WILDCARD, 
            style=wx.FLP_OPEN|wx.FLP_USE_TEXTCTRL|wx.FLP_FILE_MUST_EXIST,
        )
        self.input_file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self.__on_input_file_changed)
        input_file_sizer.Add(self.input_file_picker, flag=wx.EXPAND)
        input_file_panel.SetSizerAndFit(input_file_sizer)
        sizer.Add(input_file_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # input video thumbnail 
        input_video_panel = wx.Panel(panel)
        input_video_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        input_video_sizer.Add(wx.StaticText(input_video_panel, label='赤い▲をドラッグして、動画のプレビュー位置を指定できます。'), flag=wx.ALIGN_CENTER)
        self.input_video_thumbnail = VideoThumbnail(input_video_panel, use_x_arrow=True)
        input_video_sizer.Add(self.input_video_thumbnail, flag=wx.ALIGN_CENTER)
        input_video_panel.SetSizerAndFit(input_video_sizer)
        sizer.Add(input_video_panel, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 1

        # preview panel + control panel
        preview_panel = wx.Panel(panel)
        preview_sizer = wx.FlexGridSizer(rows=1, cols=2, gap=wx.Size(MARGIN, 0))
        preview_sizer.AddGrowableCol(0)
        preview_sizer.AddGrowableRow(0)
        self.previewer = ImageViewer(preview_panel)
        preview_sizer.Add(self.previewer, flag=wx.EXPAND)
        control_panel = self.__make_control_panel(preview_panel)
        preview_sizer.Add(control_panel, flag=wx.EXPAND)
        preview_panel.SetSizerAndFit(preview_sizer)
        sizer.Add(preview_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        sizer.AddGrowableRow(row)
        row += 1

        # output video thumbnail 
        output_video_panel = wx.Panel(panel)
        output_video_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        self.output_video_thumbnail = VideoThumbnail(output_video_panel)
        output_video_sizer.Add(self.output_video_thumbnail, flag=wx.ALIGN_CENTER)
        output_video_panel.SetSizerAndFit(output_video_sizer)
        sizer.Add(output_video_panel, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 1

        # output file panel
        output_file_panel = wx.Panel(panel)
        output_file_sizer = wx.FlexGridSizer(cols=3, gap=wx.Size(MARGIN, 0))
        output_file_sizer.AddGrowableCol(1)
        output_file_sizer.Add(wx.StaticText(output_file_panel, label='出力した連続画像のカタログファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.output_filename_text = wx.TextCtrl(output_file_panel, value='', style=wx.TE_READONLY)
        output_file_sizer.Add(self.output_filename_text, flag=wx.EXPAND)
        folder_button = wx.Button(output_file_panel, label='フォルダを開く')
        folder_button.Bind(wx.EVT_BUTTON, self.__on_folder_button_clicked)
        output_file_sizer.Add(folder_button, flag=wx.ALIGN_CENTER_VERTICAL)
        output_file_panel.SetSizerAndFit(output_file_sizer)
        sizer.Add(output_file_panel, flag=wx.EXPAND)
        row += 1

        panel.SetSizer(sizer)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=16)
        self.SetSizerAndFit(frame_sizer)

        self.color_control_changed_time = None
        self.color_control_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.__on_color_control_timer)
        self.color_control_timer.Start(100)

        self.input_video_thumbnail.Bind(EVT_VIDEO_LOADED, self.__on_video_loaded)
        self.input_video_thumbnail.Bind(EVT_VIDEO_POSITION_CHANGED, self.__on_video_position_changed)
        self.previewer.Bind(EVT_MOUSE_OVER_IMAGE, self.__on_mouse_over_image)
        self.Bind(wx.EVT_CLOSE, self.__on_close)

    def __make_control_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        sizer.AddGrowableCol(0)
        row = 0

        # video histogram
        sizer.Add(wx.StaticText(panel, label='動画のヒストグラム:'))
        self.input_video_histogram_view = HistogramView(panel)
        sizer.Add(self.input_video_histogram_view, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        self.input_video_thumbnail.set_histogram_view(self.input_video_histogram_view)
        row += 1
        
        # image histogram
        sizer.Add(wx.StaticText(panel, label='画像のヒストグラム:'))
        self.image_histogram_view = HistogramView(panel)
        sizer.Add(self.image_histogram_view, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # image information
        info_panel = wx.Panel(panel)
        info_sizer = wx.FlexGridSizer(rows=3, cols=4, gap=wx.Size(4, 0))
        info_sizer.AddGrowableCol(0, proportion=2)
        info_sizer.AddGrowableCol(1, proportion=3)
        info_sizer.AddGrowableCol(2, proportion=2)
        info_sizer.AddGrowableCol(3, proportion=1)
        info_sizer.Add(wx.StaticText(info_panel, label='フレーム位置:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.info_frame = wx.StaticText(info_panel, label='', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE)
        info_sizer.Add(self.info_frame, flag=wx.EXPAND|wx.RIGHT, border=MARGIN)
        info_sizer.Add(wx.StaticText(info_panel, label='R:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.info_r = wx.StaticText(info_panel, label='', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE)
        info_sizer.Add(self.info_r, flag=wx.EXPAND|wx.RIGHT, border=MARGIN)
        info_sizer.Add(wx.StaticText(info_panel, label='X:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.info_x = wx.StaticText(info_panel, label='', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE)
        info_sizer.Add(self.info_x, flag=wx.EXPAND|wx.RIGHT, border=MARGIN)
        info_sizer.Add(wx.StaticText(info_panel, label='G:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.info_g = wx.StaticText(info_panel, label='', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE)
        info_sizer.Add(self.info_g, flag=wx.EXPAND|wx.RIGHT, border=MARGIN)
        info_sizer.Add(wx.StaticText(info_panel, label='Y:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.info_y = wx.StaticText(info_panel, label='', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE)
        info_sizer.Add(self.info_y, flag=wx.EXPAND|wx.RIGHT, border=MARGIN)
        info_sizer.Add(wx.StaticText(info_panel, label='B:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.info_b = wx.StaticText(info_panel, label='', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE)
        info_sizer.Add(self.info_b, flag=wx.EXPAND|wx.RIGHT, border=MARGIN)
        info_panel.SetSizerAndFit(info_sizer)
        sizer.Add(info_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # rotation
        rotation_panel = wx.Panel(panel)
        rotation_sizer = wx.GridSizer(cols=5, gap=wx.Size(MARGIN, 0))
        rotation_sizer.Add(wx.StaticText(rotation_panel, label='回転:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        style = wx.RB_GROUP
        rot = str(self.rotation)
        self.rotation_buttons = {}
        for l, n in (('0°', '0'), ('90°', '90'), ('180°', '180'), ('270°', '270')):
            rotation_button = wx.RadioButton(rotation_panel, label=l, name=n, style=style)
            self.rotation_buttons[n] = rotation_button
            style = 0
            if n == rot:
                rotation_button.SetValue(True)
            rotation_sizer.Add(rotation_button, flag=wx.EXPAND)
            rotation_button.Bind(wx.EVT_RADIOBUTTON, self.__on_rotation_changed)
        rotation_panel.SetSizerAndFit(rotation_sizer)
        sizer.Add(rotation_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # color adjustment
        color_adjustment_panel = wx.Panel(panel)
        color_adjustment_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(4, MARGIN - 6))
        color_adjustment_sizer.AddGrowableCol(1)

        # color adjustment: eq
        self.eq_button = wx.ToggleButton(color_adjustment_panel, label='eq')
        color_adjustment_sizer.Add(self.eq_button, flag=wx.EXPAND|wx.TOP, border=6)
        color_eq_panel = wx.Panel(color_adjustment_panel)
        color_eq_sizer = wx.GridSizer(cols=4, gap=wx.Size(4, 2))
        color_eq_sizer.Add(wx.StaticText(color_eq_panel, label='brightness:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        color_eq_sizer.Add(wx.StaticText(color_eq_panel, label='contrast:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        color_eq_sizer.Add(wx.StaticText(color_eq_panel, label='gamma:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        color_eq_sizer.Add(wx.StaticText(color_eq_panel, label='saturation:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        self.eq_brightness = wx.SpinCtrlDouble(color_eq_panel, value="0.00", min=-1.0, max=1.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_eq_sizer.Add(self.eq_brightness, flag=wx.EXPAND)
        self.eq_contrast = wx.SpinCtrlDouble(color_eq_panel, value="1.00", min=-1000.0, max=1000.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_eq_sizer.Add(self.eq_contrast, flag=wx.EXPAND)
        self.eq_gamma = wx.SpinCtrlDouble(color_eq_panel, value="1.00", min=0.1, max=10.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_eq_sizer.Add(self.eq_gamma, flag=wx.EXPAND)
        self.eq_saturation = wx.SpinCtrlDouble(color_eq_panel, value="1.00", min=0.1, max=3.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_eq_sizer.Add(self.eq_saturation, flag=wx.EXPAND)
        color_eq_panel.SetSizerAndFit(color_eq_sizer)
        color_adjustment_sizer.Add(color_eq_panel, flag=wx.EXPAND)

        # color adjustment: colortemperature
        self.colortemperature_button = wx.ToggleButton(color_adjustment_panel, label='colortemperature')
        color_adjustment_sizer.Add(self.colortemperature_button, flag=wx.EXPAND|wx.TOP, border=6)
        color_colortemperature_panel = wx.Panel(color_adjustment_panel)
        color_colortemperature_sizer = wx.GridSizer(cols=3, gap=wx.Size(4, 2))
        color_colortemperature_sizer.Add(wx.StaticText(color_colortemperature_panel, label='temperature:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        color_colortemperature_sizer.Add(wx.StaticText(color_colortemperature_panel, label='pl:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        color_colortemperature_sizer.Add(wx.StaticText(color_colortemperature_panel, label='mix:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        self.colortemperature_temperature = wx.SpinCtrl(color_colortemperature_panel, value="6500", min=1000, max=40000, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_colortemperature_sizer.Add(self.colortemperature_temperature, flag=wx.EXPAND)
        self.colortemperature_pl = wx.SpinCtrlDouble(color_colortemperature_panel, value="1.00", min=0.0, max=1.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_colortemperature_sizer.Add(self.colortemperature_pl, flag=wx.EXPAND)
        self.colortemperature_mix = wx.SpinCtrlDouble(color_colortemperature_panel, value="1.00", min=0.0, max=1.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_colortemperature_sizer.Add(self.colortemperature_mix, flag=wx.EXPAND)
        color_colortemperature_panel.SetSizerAndFit(color_colortemperature_sizer)
        color_adjustment_sizer.Add(color_colortemperature_panel, flag=wx.EXPAND)

        # color adjustment: huesaturation
        self.huesaturation_button = wx.ToggleButton(color_adjustment_panel, label='huesaturation')
        color_adjustment_sizer.Add(self.huesaturation_button, flag=wx.EXPAND|wx.TOP, border=6)
        color_huesaturation_panel = wx.Panel(color_adjustment_panel)
        color_huesaturation_sizer = wx.GridSizer(cols=3, gap=wx.Size(4, 2))
        color_huesaturation_sizer.Add(wx.StaticText(color_huesaturation_panel, label='hue:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        color_huesaturation_sizer.Add(wx.StaticText(color_huesaturation_panel, label='saturation:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        color_huesaturation_sizer.Add(wx.StaticText(color_huesaturation_panel, label='intensity:', style=wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_BOTTOM)
        self.huesaturation_hue = wx.SpinCtrl(color_huesaturation_panel, value="0", min=-180, max=180, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_huesaturation_sizer.Add(self.huesaturation_hue, flag=wx.EXPAND)
        self.huesaturation_saturation = wx.SpinCtrlDouble(color_huesaturation_panel, value="0.00", min=-1.0, max=1.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_huesaturation_sizer.Add(self.huesaturation_saturation, flag=wx.EXPAND)
        self.huesaturation_intensity = wx.SpinCtrlDouble(color_huesaturation_panel, value="0.00", min=-1.0, max=1.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        color_huesaturation_sizer.Add(self.huesaturation_intensity, flag=wx.EXPAND)
        color_huesaturation_panel.SetSizerAndFit(color_huesaturation_sizer)
        color_adjustment_sizer.Add(color_huesaturation_panel, flag=wx.EXPAND)

        self.__update_color_adjustment_controls()

        color_adjustment_panel.SetSizerAndFit(color_adjustment_sizer)
        sizer.Add(color_adjustment_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # reload button
        reload_button = wx.Button(panel, label='設定を反映して動画を再読み込みする')
        sizer.Add(reload_button, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 1

        # output panel
        line = wx.StaticLine(panel)
        sizer.Add(line, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1
        output_panel = wx.Panel(panel)
        output_sizer = wx.FlexGridSizer(cols=3, gap=wx.Size(MARGIN, 0))
        self.format_png_button = wx.RadioButton(output_panel, label='24bit PNG', style=wx.RB_GROUP)
        self.format_png_button.SetValue(True)
        output_sizer.Add(self.format_png_button, flag=wx.RIGHT, border=MARGIN)
        self.format_tiff_button = wx.RadioButton(output_panel, label='48bit TIFF')
        output_sizer.Add(self.format_tiff_button, flag=wx.RIGHT, border=MARGIN)
        save_button = wx.Button(output_panel, label='連続画像とカタログファイルを作成する...')
        save_button.Bind(wx.EVT_BUTTON, self.__on_save_button_clicked)
        output_sizer.Add(save_button, flag=wx.ALIGN_CENTER)
        output_panel.SetSizerAndFit(output_sizer)
        sizer.Add(output_panel, flag=wx.ALIGN_CENTER)
        row += 1

        # event bindings
        self.eq_button.Bind(wx.EVT_TOGGLEBUTTON, self.__on_color_adjustment_control_changed)
        self.eq_brightness.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.eq_brightness.Bind(wx.EVT_SPINCTRLDOUBLE, self.__on_color_adjustment_changed)
        self.eq_contrast.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.eq_contrast.Bind(wx.EVT_SPINCTRLDOUBLE, self.__on_color_adjustment_changed)
        self.eq_gamma.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.eq_gamma.Bind(wx.EVT_SPINCTRLDOUBLE, self.__on_color_adjustment_changed)
        self.eq_saturation.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.eq_saturation.Bind(wx.EVT_SPINCTRLDOUBLE, self.__on_color_adjustment_changed)

        self.colortemperature_button.Bind(wx.EVT_TOGGLEBUTTON, self.__on_color_adjustment_control_changed)
        self.colortemperature_temperature.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.colortemperature_temperature.Bind(wx.EVT_SPINCTRL, self.__on_color_adjustment_changed)
        self.colortemperature_pl.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.colortemperature_pl.Bind(wx.EVT_SPINCTRLDOUBLE, self.__on_color_adjustment_changed)
        self.colortemperature_mix.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.colortemperature_mix.Bind(wx.EVT_SPINCTRLDOUBLE, self.__on_color_adjustment_changed)

        self.huesaturation_button.Bind(wx.EVT_TOGGLEBUTTON, self.__on_color_adjustment_control_changed)
        self.huesaturation_hue.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.huesaturation_hue.Bind(wx.EVT_SPINCTRL, self.__on_color_adjustment_changed)
        self.huesaturation_saturation.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.huesaturation_saturation.Bind(wx.EVT_SPINCTRLDOUBLE, self.__on_color_adjustment_changed)
        self.huesaturation_intensity.Bind(wx.EVT_TEXT, self.__on_color_adjustment_changed)
        self.huesaturation_intensity.Bind(wx.EVT_SPINCTRLDOUBLE, self.__on_color_adjustment_changed)

        reload_button.Bind(wx.EVT_BUTTON, self.__on_reload_button_clicked)

        panel.SetSizerAndFit(sizer)
        return panel
    
    def __set_previewer(self, position, filter_complex=None):
        path = Path(self.input_file_picker.GetPath())
        if not str(path) or not path.exists():
            return
        self.SetCursor(wx.Cursor(wx.CURSOR_WAIT))
        try:
            stream = ffmpeg.input(path, ss=position / self.probe.fps).video
            if filter_complex:
                for k, v in filter_complex.items():
                    if type(v) == dict:
                        stream = stream.filter_(k, **v)
                    elif type(v) == list or type(v) == tuple:
                        stream = stream.filter_(k, *v)
                    else:
                        stream = stream.filter_(k, v)
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
            self.frame = np.frombuffer(out, np.uint8).reshape(h, w, 3)
            frame = self.__rotate_frame(self.frame)
            self.previewer.set_image(frame)
            self.image_histogram_view.begin_histogram()
            self.image_histogram_view.add_histogram(self.frame)
            self.image_histogram_view.end_histogram()
            self.image_histogram_view.update_view()
        except Exception as e:
            wx.MessageBox(f'画像の取り出しに失敗しました:\n{e}', TOOL_NAME, wx.OK|wx.ICON_ERROR)
        finally:
            self.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))

    def __rotate_frame(self, frame):
        if self.rotation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        elif self.rotation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def __update_color_adjustment_controls(self):
        if self.eq_button.GetValue():
            self.eq_brightness.Enable()
            self.eq_contrast.Enable()
            self.eq_gamma.Enable()
            self.eq_saturation.Enable()
        else:
            self.eq_brightness.Disable()
            self.eq_contrast.Disable()
            self.eq_gamma.Disable()
            self.eq_saturation.Disable()
        if self.colortemperature_button.GetValue():
            self.colortemperature_temperature.Enable()
            self.colortemperature_pl.Enable()
            self.colortemperature_mix.Enable()
        else:
            self.colortemperature_temperature.Disable()
            self.colortemperature_pl.Disable()
            self.colortemperature_mix.Disable()
        if self.huesaturation_button.GetValue():
            self.huesaturation_hue.Enable()
            self.huesaturation_saturation.Enable()
            self.huesaturation_intensity.Enable()
        else:
            self.huesaturation_hue.Disable()
            self.huesaturation_saturation.Disable()
            self.huesaturation_intensity.Disable()

    def __get_spin_ctrl_value(self, spin_ctrl):
        value = spin_ctrl.GetTextValue()
        if len(value) == 0:
            return spin_ctrl.GetValue()
        _min, _max = spin_ctrl.GetMin(), spin_ctrl.GetMax()
        if type(_min) == int:
            value = int(value)
        else:
            value = float(value)
        return min(max(_min, value), _max)

    def __make_filter_complex(self):
        filter_complex = {}
        if self.eq_button.GetValue():
            filter_complex['eq'] = dict(
                brightness=self.__get_spin_ctrl_value(self.eq_brightness),
                contrast=self.__get_spin_ctrl_value(self.eq_contrast),
                gamma=self.__get_spin_ctrl_value(self.eq_gamma),
                saturation=self.__get_spin_ctrl_value(self.eq_saturation),
            )
        if self.colortemperature_button.GetValue():
            filter_complex['colortemperature'] = dict(
                temperature=self.__get_spin_ctrl_value(self.colortemperature_temperature),
                pl=self.__get_spin_ctrl_value(self.colortemperature_pl),
                mix=self.__get_spin_ctrl_value(self.colortemperature_mix),
            )
        if self.huesaturation_button.GetValue():
            filter_complex['huesaturation'] = dict(
                hue=self.__get_spin_ctrl_value(self.huesaturation_hue),
                saturation=self.__get_spin_ctrl_value(self.huesaturation_saturation),
                intensity=self.__get_spin_ctrl_value(self.huesaturation_intensity),
            )
        print(f'{filter_complex=}')
        return filter_complex

    def __make_setting_file_path(self):
        path = Path(self.input_file_picker.GetPath())
        if not path.exists():
            return None
        return path.with_suffix(SETTING_EXTENSION)

    def __save_setting(self):
        path = self.__make_setting_file_path()
        if not path:
            return
        setting = dict(
            rotation=self.rotation,
            eq=self.eq_button.GetValue(),
            eq_brightness=self.__get_spin_ctrl_value(self.eq_brightness),
            eq_contrast=self.__get_spin_ctrl_value(self.eq_contrast),
            eq_gamma=self.__get_spin_ctrl_value(self.eq_gamma),
            eq_saturation=self.__get_spin_ctrl_value(self.eq_saturation),
            colortemperature=self.colortemperature_button.GetValue(),
            colortemperature_temperature=self.__get_spin_ctrl_value(self.colortemperature_temperature),
            colortemperature_pl=self.__get_spin_ctrl_value(self.colortemperature_pl),
            colortemperature_mix=self.__get_spin_ctrl_value(self.colortemperature_mix),
            huesaturation=self.huesaturation_button.GetValue(),
            huesaturation_hue=self.__get_spin_ctrl_value(self.huesaturation_hue),
            huesaturation_saturation=self.__get_spin_ctrl_value(self.huesaturation_saturation),
            huesaturation_intensity=self.__get_spin_ctrl_value(self.huesaturation_intensity),
        )
        with open(path, 'w') as f:
            json.dump(setting, f, indent=2)

    def __load_setting(self):
        path = self.__make_setting_file_path()
        if not path:
            return
        if not path.exists():
            return
        def _g(setting, name, default_value):
            if name not in setting:
                return default_value
            if type(setting[name]) == float:
                return f'{setting[name]:.2f}'
            return setting[name]
        with open(path, 'r') as f:
            setting = json.load(f)
        self.rotation = _g(setting, 'rotation', 0)
        self.eq_button.SetValue(_g(setting, 'eq', False))
        self.eq_brightness.SetValue(_g(setting, 'eq_brightness', '0.00'))
        self.eq_contrast.SetValue(_g(setting, 'eq_contrast', '1.00'))
        self.eq_gamma.SetValue(_g(setting, 'eq_gamma', '1.00'))
        self.eq_saturation.SetValue(_g(setting, 'eq_saturation', '1.00'))
        self.colortemperature_button.SetValue(_g(setting, 'colortemperature', False))
        self.colortemperature_temperature.SetValue(_g(setting, 'colortemperature_temperature', '6500'))
        self.colortemperature_pl.SetValue(_g(setting, 'colortemperature_pl', '1.00'))
        self.colortemperature_mix.SetValue(_g(setting, 'colortemperature_mix', '1.00'))
        self.huesaturation_button.SetValue(_g(setting, 'huesaturation', False))
        self.huesaturation_hue.SetValue(_g(setting, 'huesaturation_hue', '0'))
        self.huesaturation_saturation.SetValue(_g(setting, 'huesaturation_saturation', '0.00'))
        self.huesaturation_intensity.SetValue(_g(setting, 'huesaturation_intensity', '0.00'))
        self.rotation_buttons[str(self.rotation)].SetValue(True)
        self.__update_color_adjustment_controls()

    def __load_video(self):
        path = Path(self.input_file_picker.GetPath())
        if not path.exists():
            return
        self.probe = Probe(path)
        self.input_video_thumbnail.clear()
        self.input_video_histogram_view.clear()
        self.image_histogram_view.clear()
        self.previewer.clear()
        self.info_frame.SetLabel('')
        self.info_x.SetLabel('')
        self.info_y.SetLabel('')
        self.info_r.SetLabel('')
        self.info_g.SetLabel('')
        self.info_b.SetLabel('')
        self.__load_setting()
        self.input_video_thumbnail.load_video(path, self.rotation, self.__make_filter_complex())

    def __on_input_file_changed(self, event):
        self.__load_video()

    def __on_video_loaded(self, event):
        frame_count = self.input_video_thumbnail.get_frame_count()
        position = self.input_video_thumbnail.get_frame_position()
        self.__set_previewer(position, self.__make_filter_complex())
        self.input_video_histogram_view.update_view()
        self.info_frame.SetLabel(f'{position}/{frame_count}')
        event.Skip()

    def __on_video_position_changed(self, event):
        self.__set_previewer(event.position, self.__make_filter_complex())
        self.info_frame.SetLabel(f'{event.position}/{event.frame_count}')

    def __on_mouse_over_image(self, event):
        x, y = event.image_x, event.image_y
        if x is None:
            self.info_x.SetLabel('')
            self.info_y.SetLabel('')
            self.info_r.SetLabel('')
            self.info_g.SetLabel('')
            self.info_b.SetLabel('')
        else:
            image = self.previewer.get_image()
            self.info_x.SetLabel(f'{x}/{image.shape[1]}')
            self.info_y.SetLabel(f'{y}/{image.shape[0]}')
            self.info_r.SetLabel(f'{image[y, x, 0]}')
            self.info_g.SetLabel(f'{image[y, x, 1]}')
            self.info_b.SetLabel(f'{image[y, x, 2]}')
        event.Skip()

    def __on_rotation_changed(self, event):
        self.rotation = int(event.GetEventObject().GetName())
        frame = self.__rotate_frame(self.frame)
        self.previewer.set_image(frame)

    def __on_color_adjustment_control_changed(self, event):
        self.__update_color_adjustment_controls()
        self.color_control_changed_time = time.time()

    def __on_color_adjustment_changed(self, event):
        self.color_control_changed_time = time.time()

    def __on_reload_button_clicked(self, event):
        self.__save_setting()
        self.__load_video()

    def __on_color_control_timer(self, event):
        if self.color_control_changed_time is None:
            return
        if time.time() - self.color_control_changed_time >= 1.0:
            self.color_control_changed_time = None
            if self.input_video_thumbnail.get_frame_count():
                position = self.input_video_thumbnail.get_frame_position()
                self.__set_previewer(position, self.__make_filter_complex())
                self.__save_setting()

    def __on_close(self, event):
        self.color_control_timer.Stop()
        self.__save_setting()
        event.Skip()

    def __on_save_button_clicked(self, event):
        if self.input_video_thumbnail.get_frame_count() == 0:
            wx.MessageBox('連続画像を取り出す動画が読み込まれていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            return

        output_format = 'TIFF' if self.format_tiff_button.GetValue() else 'PNG'
        input_path = Path(self.input_file_picker.GetPath())
        output_filename = input_path.stem.removesuffix(RAW_SUFFIX) + '_' + output_format + '.txt'

        with wx.FileDialog(
            self, 
            '保存先の連続画像のカタログファイル名を入力してください。(連続画像のディレクトリ名にもなります)', 
            defaultDir=str(input_path.parent),
            defaultFile=output_filename,
            wildcard='Image catalog files (*.txt;*.lst)|*.txt;*.lst',
            style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            self.__save_setting()
            output_path = Path(fileDialog.GetPath())
            self.output_filename_text.SetValue(str(output_path))
            self.output_video_thumbnail.load_video(
                input_path, 
                self.rotation, 
                self.__make_filter_complex(),
                output_path,
                output_format
            )

    def __on_folder_button_clicked(self, event):
        path = self.output_filename_text.GetValue()
        if not path:
            return
        path = Path(path)
        if not path.exists():
            return
        wx.LaunchDefaultApplication(str(path.parent))
