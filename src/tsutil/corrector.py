import wx
import wx.adv
from pathlib import Path
from subprocess import Popen, PIPE
from pydantic import BaseModel
import numpy as np
import cv2
from .common import *
from .tool_frame import ToolFrame
from .components.video_thumbnail import VideoThumbnail, EVT_VIDEO_LOADED, EVT_VIDEO_POSITION_CHANGED
from .components.image_viewer import ImageViewer, EVT_MOUSE_OVER_IMAGE
from .components.base_image_viewer import BaseImageViewer, EVT_FIELD_ADDED
from ffio import Probe

# MARK: constants

MARGIN = 12
TOOL_NAME = '画像のブレ・傾き・歪みの補正'
SETTING_EXTENSION = '.correct.json'
PNG_SUFFIX = '_PNG'
TIFF_SUFFIX = '_TIFF'

# MARK: correction data model

class CorrectionDataModel(BaseModel):
    base_frame_pos: int|None = None
    sample_frame_pos: int|None = None
    shaking_detection_fields: list[Rect] = []   # Rect * (0 or 1 or 3)
    rotation_angle: float|None = None
    perspective_coords: PerspectivePoints = PerspectivePoints()
    clip: Rect = Rect()

    def get_shaking_detection_field_list(self):
        return [f'{i + 1}: {str(item)}' for i, item in enumerate(self.shaking_detection_fields)]

    def get_shaking_detection_condition(self):
        count = len(self.shaking_detection_fields)
        if count == 0:
            return 'ブレ補正しません。左の画像をドラッグしてブレ測定の枠を1〜3つ追加するとブレ補正します。'
        elif count < 3:
            return 'XY方向のブレを補正します。ブレの測定枠を2つ追加した場合、最初の1つを用います。回転補正するには3つ必要です。'
        else:
            return 'XY方向と回転のブレを補正します。ブレの測定枠を4つ以上追加した場合、最初の3つを用います。'

# MARK: main window

class MainFrame(ToolFrame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=TOOL_NAME, *args, **kw)
        self.model = CorrectionDataModel()
        self.deshaking_transform = np.eye(3)
        self.transform = np.eye(3)
        self.base_frame = None
        self.sample_frame = None

        frame_sizer = wx.GridSizer(rows=1, cols=1, gap=wx.Size(0, 0))
        panel = wx.Panel(self)
        sizer = wx.FlexGridSizer(rows=0, cols=1, gap=wx.Size(0, 0))
        sizer.AddGrowableCol(0)
        row = 0

        # input file panel
        input_file_panel = wx.Panel(panel)
        input_file_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        input_file_sizer.AddGrowableCol(1)
        input_file_sizer.Add(wx.StaticText(input_file_panel, label='連続画像のカタログファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.input_file_picker = wx.FilePickerCtrl(
            input_file_panel,
            message='連続画像のカタログファイルを選択してください。',
            wildcard=IMAGE_CATALOG_FILE_WILDCARD,
            style=wx.FLP_OPEN|wx.FLP_USE_TEXTCTRL|wx.FLP_FILE_MUST_EXIST,
        )
        self.input_file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self.__on_input_file_changed)
        input_file_sizer.Add(self.input_file_picker, flag=wx.EXPAND)
        input_file_panel.SetSizerAndFit(input_file_sizer)
        sizer.Add(input_file_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # input video thumbnail panel
        input_video_panel = wx.Panel(panel)
        input_video_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))

        input_frame_panel = wx.Panel(input_video_panel)
        input_frame_sizer = wx.GridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        self.base_frame_button = wx.RadioButton(input_frame_panel, label='ブレ補正の基準画像を選択する', style=wx.RB_GROUP)
        self.base_frame_button.SetValue(True)
        input_frame_sizer.Add(self.base_frame_button, flag=wx.ALIGN_CENTER)
        self.sample_frame_button = wx.RadioButton(input_frame_panel, label='補正対象のサンプル画像を選択する')
        input_frame_sizer.Add(self.sample_frame_button, flag=wx.ALIGN_CENTER)
        input_frame_panel.SetSizerAndFit(input_frame_sizer)
        input_video_sizer.Add(input_frame_panel, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=4)

        self.input_video_thumbnail = VideoThumbnail(input_video_panel, use_x_arrow=True)
        input_video_sizer.Add(self.input_video_thumbnail, flag=wx.ALIGN_CENTER)

        input_video_panel.SetSizerAndFit(input_video_sizer)
        sizer.Add(input_video_panel, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 1

        # viewer panel
        viewer_panel = self.__make_viewer_panel(panel)
        sizer.Add(viewer_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        sizer.AddGrowableRow(row)
        row += 1

        # shaking detection condition
        shaking_detection_panel = wx.Panel(panel)
        shaking_detection_sizer = wx.BoxSizer(orient=wx.HORIZONTAL)
        shaking_detection_sizer.Add(wx.StaticText(shaking_detection_panel, label='ブレ補正:'), flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=4)
        self.shaking_detection_condition_label = wx.StaticText(shaking_detection_panel, label=self.model.get_shaking_detection_condition(), style=wx.BORDER_SIMPLE)
        shaking_detection_sizer.Add(self.shaking_detection_condition_label, flag=wx.ALIGN_CENTER_VERTICAL)
        shaking_detection_panel.SetSizerAndFit(shaking_detection_sizer)
        sizer.Add(shaking_detection_panel, flag=wx.EXPAND|wx.BOTTOM, border=4)
        row += 1

        # console panel
        console_panel = self.__make_console_panel(panel)
        sizer.Add(console_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
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

        self.setting_changed_time = None
        self.setting_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.__on_setting_timer)
        self.setting_timer.Start(100)

        self.input_video_thumbnail.Bind(EVT_VIDEO_LOADED, self.__on_video_loaded)
        self.input_video_thumbnail.Bind(EVT_VIDEO_POSITION_CHANGED, self.__on_video_position_changed)
        self.base_frame_button.Bind(wx.EVT_RADIOBUTTON, self.__on_base_frame_button_clicked)
        self.sample_frame_button.Bind(wx.EVT_RADIOBUTTON, self.__on_sample_frame_button_clicked)
        self.Bind(wx.EVT_CLOSE, self.__on_close)

    def __make_viewer_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(MARGIN, 0))
        sizer.AddGrowableCol(0, proportion=2)
        row = 0

        # captions
        caption_panel = wx.Panel(panel)
        caption_sizer = wx.GridSizer(cols=3, gap=wx.Size(MARGIN, 0))
        caption_sizer.Add(wx.StaticText(caption_panel, label='ブレ補正の基準画像とブレ測定枠の設定:'), flag=wx.ALIGN_CENTER)
        caption_sizer.Add(wx.StaticText(caption_panel, label='ブレ補正後のサンプル画像と画像補正の設定'), flag=wx.ALIGN_CENTER)
        caption_sizer.Add(wx.StaticText(caption_panel, label='画像補正後のサンプル画像'), flag=wx.ALIGN_CENTER)
        caption_panel.SetSizerAndFit(caption_sizer)
        sizer.Add(caption_panel, flag=wx.EXPAND)
        row += 1

        # image viewers
        image_panel = wx.Panel(panel)
        image_sizer = wx.GridSizer(cols=3, gap=wx.Size(MARGIN, 0))
        self.base_image_viewer = BaseImageViewer(image_panel, self.model.shaking_detection_fields)
        self.base_image_viewer.Bind(EVT_FIELD_ADDED, self.__on_field_added)
        image_sizer.Add(self.base_image_viewer, flag=wx.EXPAND)
        self.deshake_image_viewer = ImageViewer(image_panel)
        image_sizer.Add(self.deshake_image_viewer, flag=wx.EXPAND)
        self.clip_image_viewer = ImageViewer(image_panel)
        image_sizer.Add(self.clip_image_viewer, flag=wx.EXPAND)
        image_panel.SetSizerAndFit(image_sizer)
        sizer.Add(image_panel, flag=wx.EXPAND)
        sizer.AddGrowableRow(row)
        row += 1

        panel.SetSizerAndFit(sizer)
        return panel

    def __make_console_panel(self, main_panel):
        panel = wx.Panel(main_panel)
        sizer = wx.GridSizer(cols=3, gap=wx.Size(MARGIN, 0))

        # shaking detection field list
        shaking_panel = wx.Panel(panel)
        shaking_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(4, 0))
        shaking_sizer.AddGrowableRow(0)
        shaking_sizer.AddGrowableCol(0)
        self.shaking_detection_area_listbox = wx.ListBox(shaking_panel, style=wx.LB_SINGLE)
        self.shaking_detection_area_listbox.Bind(wx.EVT_LISTBOX, self.__on_shaking_detection_area_listbox)
        shaking_sizer.Add(self.shaking_detection_area_listbox, flag=wx.EXPAND)
        button_panel = wx.Panel(shaking_panel)
        button_sizer = wx.GridSizer(cols=1, gap=wx.Size(0, 0))
        self.shaking_detection_area_add_button = wx.ToggleButton(button_panel, label='追加')
        self.shaking_detection_area_add_button.SetValue(False)
        self.shaking_detection_area_add_button.Disable()
        self.shaking_detection_area_add_button.Bind(wx.EVT_TOGGLEBUTTON, self.__on_shaking_detection_area_add_button_clicked)
        button_sizer.Add(self.shaking_detection_area_add_button, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=4)
        self.shaking_detection_area_del_button = wx.Button(button_panel, label='削除')
        self.shaking_detection_area_del_button.Disable()
        self.shaking_detection_area_del_button.Bind(wx.EVT_BUTTON, self.__on_shaking_detection_area_del_button_clicked)
        button_sizer.Add(self.shaking_detection_area_del_button, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=4)
        button_panel.SetSizerAndFit(button_sizer)
        shaking_sizer.Add(button_panel, flag=wx.ALIGN_TOP)
        shaking_panel.SetSizerAndFit(shaking_sizer)
        sizer.Add(shaking_panel, flag=wx.EXPAND)

        # corretion setting
        correction_panel = wx.Panel(panel)
        correction_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        correction_sizer.AddGrowableCol(0)
        rotation_panel = wx.Panel(correction_panel)
        rotation_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(4, 0))
        rotation_sizer.Add(wx.StaticText(rotation_panel, label='基準画像の回転を補正する角度:', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL)
        self.rotation = wx.SpinCtrlDouble(rotation_panel, value='0.00', min=-180.0, max=180.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        rotation_sizer.Add(self.rotation, flag=wx.EXPAND)
        rotation_panel.SetSizerAndFit(rotation_sizer)
        correction_sizer.Add(rotation_panel, flag=wx.ALIGN_CENTER_HORIZONTAL|wx.TOP|wx.BOTTOM, border=6)
        correction_sizer.Add(wx.StaticText(correction_panel, label='歪み補正(射影変換)は中央の画像の□を動かして', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        correction_sizer.Add(wx.StaticText(correction_panel, label='水平・垂直にする領域を設定します。', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        correction_panel.SetSizerAndFit(correction_sizer)
        sizer.Add(correction_panel, flag=wx.EXPAND)

        # clip setting
        clip_panel = wx.Panel(panel)
        clip_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        clip_sizer.AddGrowableCol(0)
        clip_sizer.Add(wx.StaticText(clip_panel, label='補正画像は右の画像の□を動かして', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        clip_sizer.Add(wx.StaticText(clip_panel, label='画像ファイルに保存する領域を設定します。', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        clip_sizer.AddStretchSpacer()
        clip_sizer.AddGrowableRow(2)
        save_button = wx.Button(clip_panel, label='補正後の連続画像とカタログファイルを作成する...')
        save_button.Bind(wx.EVT_BUTTON, self.__on_save_button_clicked)
        clip_sizer.Add(save_button, flag=wx.ALIGN_CENTER)
        clip_panel.SetSizerAndFit(clip_sizer)
        sizer.Add(clip_panel, flag=wx.EXPAND)

        panel.SetSizerAndFit(sizer)
        return panel

    def __set_base_image_viewer(self):
        image_catalog = self.input_video_thumbnail.get_image_catalog()
        if image_catalog is None or self.model.base_frame_pos is None or self.model.base_frame_pos >= len(image_catalog):
            return
        self.base_frame = cv2.cvtColor(cv2.imread(str(image_catalog[self.model.base_frame_pos])), cv2.COLOR_BGR2RGB)
        frame = (self.base_frame // 256).astype(np.uint8)  if self.base_frame.dtype == np.uint16 else self.base_frame
        self.base_image_viewer.set_image(frame)

    def __set_sample_image_viewer(self):
        image_catalog = self.input_video_thumbnail.get_image_catalog()
        if image_catalog is None or self.model.sample_frame_pos is None or self.model.sample_frame_pos >= len(image_catalog):
            return
        self.sample_frame = cv2.cvtColor(cv2.imread(str(image_catalog[self.model.sample_frame_pos])), cv2.COLOR_BGR2RGB)
        frame = (self.sample_frame // 256).astype(np.uint8)  if self.sample_frame.dtype == np.uint16 else self.sample_frame

        self.deshake_image_viewer.set_image(frame)
        self.clip_image_viewer.set_image(frame)

    def __sync_shaking_detection_area_listbox(self):
        field_list = self.model.get_shaking_detection_field_list()
        self.shaking_detection_area_listbox.Set(field_list)
        self.shaking_detection_condition_label.SetLabel(self.model.get_shaking_detection_condition())

    def __make_setting_file_path(self):
        path = get_path(self.input_file_picker.GetPath())
        if not path_exists(path):
            return None
        return path.with_suffix(SETTING_EXTENSION)

    def __save_setting(self):
        pass

    def __load_setting(self):
        pass

    def __load_image_catalog(self):
        path = get_path(self.input_file_picker.GetPath())
        if not path_exists(path):
            return
        self.input_video_thumbnail.clear()
        self.base_image_viewer.clear()
        self.deshake_image_viewer.clear()
        self.clip_image_viewer.clear()
        self.shaking_detection_area_listbox.Clear()
        self.shaking_detection_area_del_button.Disable()
        self.rotation.SetValue('0.00')
        self.output_video_thumbnail.clear()
        self.output_filename_text.SetValue('')
        self.__load_setting()
        self.input_video_thumbnail.load_image_catalog(path)

    def __on_input_file_changed(self, event):
        self.__load_image_catalog()

    def __on_video_loaded(self, event):
        position = self.input_video_thumbnail.get_frame_position()
        count = self.input_video_thumbnail.get_frame_count()
        if self.model.base_frame_pos is None or self.model.base_frame_pos >= count:
            self.model.base_frame_pos = position
        if self.model.sample_frame_pos is None or self.model.sample_frame_pos >= count:
            self.model.sample_frame_pos = position
        self.__set_base_image_viewer()
        self.__set_sample_image_viewer()
        self.__sync_shaking_detection_area_listbox()
        self.shaking_detection_area_add_button.Enable()
        event.Skip()

    def __on_video_position_changed(self, event):
        if self.base_frame_button.GetValue():
            self.model.base_frame_pos = event.position
            self.__set_base_image_viewer()
        elif self.sample_frame_button.GetValue():
            self.model.sample_frame_pos = event.position
            self.__set_sample_image_viewer()
        event.Skip()

    def __on_base_frame_button_clicked(self, event):
        count = self.input_video_thumbnail.get_frame_count()
        if self.model.base_frame_pos is None or self.model.base_frame_pos >= count:
            return
        self.input_video_thumbnail.set_frame_position(self.model.base_frame_pos)

    def __on_sample_frame_button_clicked(self, event):
        count = self.input_video_thumbnail.get_frame_count()
        if self.model.sample_frame_pos is None or self.model.sample_frame_pos >= count:
            return
        self.input_video_thumbnail.set_frame_position(self.model.sample_frame_pos)

    def __on_field_added(self, event):
        sz = event.field.get_size()
        if sz[0] * sz[1]:
            self.model.shaking_detection_fields.append(event.field)
            self.__sync_shaking_detection_area_listbox()
            self.shaking_detection_area_listbox.EnsureVisible(len(self.model.shaking_detection_fields) - 1)
        self.shaking_detection_area_add_button.SetValue(False)
        self.base_image_viewer.set_field_add_mode(False)

    def __on_shaking_detection_area_listbox(self, event):
        sel = self.shaking_detection_area_listbox.GetSelection()
        if sel == wx.NOT_FOUND:
            self.shaking_detection_area_del_button.Disable()
        else:
            self.shaking_detection_area_del_button.Enable()
            self.base_image_viewer.show_field(self.model.shaking_detection_fields[sel])

    def __on_shaking_detection_area_add_button_clicked(self, event):
        value = self.shaking_detection_area_add_button.GetValue()
        self.base_image_viewer.set_field_add_mode(value)

    def __on_shaking_detection_area_del_button_clicked(self, event):
        sel = self.shaking_detection_area_listbox.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        self.model.shaking_detection_fields.pop(sel)
        self.__sync_shaking_detection_area_listbox()
        self.base_image_viewer.Refresh()
        self.shaking_detection_area_del_button.Disable()

    def __on_setting_timer(self, event):
        event.Skip()

    def __on_close(self, event):
        self.setting_timer.Stop()
        self.__save_setting()
        event.Skip()

    def __on_save_button_clicked(self, event):
        pass

    def __on_folder_button_clicked(self, event):
        path = get_path(self.output_filename_text.GetValue())
        if not path_exists(path):
            return
        wx.LaunchDefaultApplication(str(path.parent))
