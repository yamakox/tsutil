import wx
import wx.adv
from pathlib import Path
from subprocess import Popen, PIPE
from pydantic import BaseModel
import numpy as np
import cv2
import time
from .common import *
from .tool_frame import ToolFrame
from .components.video_thumbnail import VideoThumbnail, EVT_VIDEO_LOADED, EVT_VIDEO_POSITION_CHANGED
from .components.image_viewer import ImageViewer
from .components.base_image_viewer import BaseImageViewer, EVT_FIELD_ADDED, EVT_FIELD_DELETED
from .components.deshaking_image_viewer import DeshakingImageViewer, EVT_PERSPECTIVE_POINTS_CHANGED
from .components.clip_image_viewer import ClipImageViewer, EVT_CLIP_RECT_CHANGED
from .functions import DeshakingCorrection

# MARK: constants

MARGIN = 12
TOOL_NAME = '連続画像のブレ・傾き・歪みの補正'
SETTING_EXTENSION = '.correct.json'
CORR_SUFFIX = '_CORR'
PNG_SUFFIX = '_PNG'
TIFF_SUFFIX = '_TIFF'

# MARK: main window

class MainFrame(ToolFrame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=TOOL_NAME, *args, **kw)
        self.model = CorrectionDataModel()
        self.deshaking_correction = DeshakingCorrection()
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
        sizer.Add(viewer_panel, flag=wx.EXPAND)
        sizer.AddGrowableRow(row)
        row += 1

        # console panel
        console_panel = self.__make_console_panel(panel)
        sizer.Add(console_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # use correction panel
        use_correction_panel = wx.Panel(panel)
        user_correction_sizer = wx.BoxSizer(orient=wx.HORIZONTAL)
        self.use_deshake_correction_button = wx.CheckBox(use_correction_panel, label='ブレ補正を行う')
        self.use_deshake_correction_button.SetValue(self.model.use_deshake_correction)
        self.use_deshake_correction_button.Bind(wx.EVT_CHECKBOX, self.__on_input_value_changed)
        user_correction_sizer.Add(self.use_deshake_correction_button, flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=MARGIN)
        self.use_overlay_button = wx.CheckBox(use_correction_panel, label='基準画像を重ねて表示する')
        self.use_overlay_button.SetValue(self.model.use_overlay)
        self.use_overlay_button.Bind(wx.EVT_CHECKBOX, self.__on_input_value_changed)
        user_correction_sizer.Add(self.use_overlay_button, flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=MARGIN)
        self.use_nega_button = wx.CheckBox(use_correction_panel, label='ネガで重ねる')
        self.use_nega_button.SetValue(self.model.use_nega)
        self.use_nega_button.Bind(wx.EVT_CHECKBOX, self.__on_input_value_changed)
        user_correction_sizer.Add(self.use_nega_button, flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=MARGIN)
        self.use_rotation_correction_button = wx.CheckBox(use_correction_panel, label='画像の傾き補正(角度):')
        self.use_rotation_correction_button.SetValue(self.model.use_rotation_correction)
        self.use_rotation_correction_button.Bind(wx.EVT_CHECKBOX, self.__on_input_value_changed)
        user_correction_sizer.Add(self.use_rotation_correction_button, flag=wx.ALIGN_CENTER_VERTICAL)
        self.rotation = wx.SpinCtrlDouble(use_correction_panel, value='0.00', min=-180.0, max=180.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        self.rotation.Bind(wx.EVT_TEXT, self.__on_input_value_changed)
        self.rotation.Bind(wx.EVT_SPINCTRLDOUBLE, self.__on_input_value_changed)
        user_correction_sizer.Add(self.rotation, flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=MARGIN)
        self.use_perspective_correction_button = wx.CheckBox(use_correction_panel, label='歪み補正(射影変換)を行う')
        self.use_perspective_correction_button.SetValue(self.model.use_perspective_correction)
        self.use_perspective_correction_button.Bind(wx.EVT_CHECKBOX, self.__on_input_value_changed)
        user_correction_sizer.Add(self.use_perspective_correction_button, flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=MARGIN)
        self.use_grid_button = wx.CheckBox(use_correction_panel, label='グリッドを表示する')
        self.use_grid_button.SetValue(self.model.use_grid)
        self.use_grid_button.Bind(wx.EVT_CHECKBOX, self.__on_input_value_changed)
        user_correction_sizer.Add(self.use_grid_button, flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=MARGIN)
        use_correction_panel.SetSizerAndFit(user_correction_sizer)
        sizer.Add(use_correction_panel, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 1

        # save button
        save_button = wx.Button(panel, label='補正後の連続画像とカタログファイルを作成する...')
        save_button.Bind(wx.EVT_BUTTON, self.__on_save_button_clicked)
        sizer.Add(save_button, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)

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
        caption_sizer.Add(wx.StaticText(caption_panel, label='ブレ補正後のサンプル画像と歪み補正の設定:'), flag=wx.ALIGN_CENTER)
        caption_sizer.Add(wx.StaticText(caption_panel, label='画像補正後のサンプル画像と出力範囲の設定:'), flag=wx.ALIGN_CENTER)
        caption_panel.SetSizerAndFit(caption_sizer)
        sizer.Add(caption_panel, flag=wx.EXPAND)
        row += 1

        # image viewers
        image_panel = wx.Panel(panel)
        image_sizer = wx.GridSizer(cols=3, gap=wx.Size(MARGIN, 0))
        self.base_image_viewer = BaseImageViewer(image_panel, self.model.shaking_detection_fields, field_add_mode=True)
        self.base_image_viewer.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        self.base_image_viewer.Bind(EVT_FIELD_ADDED, self.__on_field_added)
        self.base_image_viewer.Bind(EVT_FIELD_DELETED, self.__on_field_deleted)
        image_sizer.Add(self.base_image_viewer, flag=wx.EXPAND)
        self.deshaking_image_viewer = DeshakingImageViewer(image_panel, self.model.perspective_points, self.model.shaking_detection_fields)
        self.deshaking_image_viewer.Bind(EVT_PERSPECTIVE_POINTS_CHANGED, self.__on_perspective_points_changed)
        image_sizer.Add(self.deshaking_image_viewer, flag=wx.EXPAND)
        self.clip_image_viewer = ClipImageViewer(image_panel, self.model.clip)
        self.clip_image_viewer.Bind(EVT_CLIP_RECT_CHANGED, self.__on_clip_rect_changed)
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

        # shaking detection setting
        shaking_panel = wx.Panel(panel)
        shaking_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        shaking_sizer.AddGrowableCol(0)
        shaking_sizer.Add(wx.StaticText(shaking_panel, label='左の画像をドラッグしてブレ測定枠を追加します。', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        shaking_sizer.Add(wx.StaticText(shaking_panel, label='また、ブレ測定枠をクリックすると削除します。', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        shaking_panel.SetSizerAndFit(shaking_sizer)
        sizer.Add(shaking_panel, flag=wx.EXPAND)

        # corretion setting
        correction_panel = wx.Panel(panel)
        correction_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        correction_sizer.AddGrowableCol(0)
        correction_sizer.Add(wx.StaticText(correction_panel, label='歪み補正(射影変換)は中央の画像の赤■を動かして', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        correction_sizer.Add(wx.StaticText(correction_panel, label='水平・垂直にする四角形を設定します。', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        correction_panel.SetSizerAndFit(correction_sizer)
        sizer.Add(correction_panel, flag=wx.EXPAND)

        # clip setting
        clip_panel = wx.Panel(panel)
        clip_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        clip_sizer.AddGrowableCol(0)
        clip_sizer.Add(wx.StaticText(clip_panel, label='右の補正後画像の赤■を動かして', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        clip_sizer.Add(wx.StaticText(clip_panel, label='画像ファイルに出力する範囲を設定します。', style=wx.ST_NO_AUTORESIZE), flag=wx.ALIGN_CENTER_HORIZONTAL)
        clip_panel.SetSizerAndFit(clip_sizer)
        sizer.Add(clip_panel, flag=wx.EXPAND)

        panel.SetSizerAndFit(sizer)
        return panel

    def __set_base_image_viewer(self):
        image_catalog = self.input_video_thumbnail.get_image_catalog()
        if image_catalog is None or self.model.base_frame_pos is None or self.model.base_frame_pos >= len(image_catalog):
            self.base_image_viewer.clear()
            return
        self.base_frame = cv2.cvtColor(cv2.imread(str(image_catalog[self.model.base_frame_pos]), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB)
        self.deshaking_correction.set_base_image(self.base_frame)
        frame = (self.base_frame // 256).astype(np.uint8)  if self.base_frame.dtype == np.uint16 else self.base_frame
        self.base_image_viewer.set_image(frame)

    def __set_sample_image_viewer(self):
        image_catalog = self.input_video_thumbnail.get_image_catalog()
        if image_catalog is None or self.model.sample_frame_pos is None or self.model.sample_frame_pos >= len(image_catalog):
            self.deshaking_image_viewer.clear()
            self.clip_image_viewer.clear()
            return
        
        # deshaking image
        self.sample_frame = cv2.cvtColor(cv2.imread(str(image_catalog[self.model.sample_frame_pos]), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB)
        if self.model.perspective_points.is_none():
            self.model.perspective_points.init(self.sample_frame)
        self.deshaking_correction.set_sample_image(self.sample_frame, self.model.sample_frame_pos)
        fields = self.model.shaking_detection_fields if self.model.use_deshake_correction else []
        angle = self.model.rotation_angle if self.model.use_rotation_correction else 0.0
        mat = self.deshaking_correction.compute(fields, angle)
        frame = (self.sample_frame // 256).astype(np.uint8)  if self.sample_frame.dtype == np.uint16 else self.sample_frame
        deshaked_frame = cv2.warpPerspective(frame, mat, (frame.shape[1], frame.shape[0]), flags=cv2.INTER_AREA)
        if self.model.use_overlay:
            if self.model.use_nega:
                deshaked_frame = deshaked_frame // 2 + (255 - self.base_frame) // 2
            else:
                deshaked_frame = deshaked_frame // 2 + self.base_frame // 2
        self.deshaking_image_viewer.set_image(deshaked_frame)
        self.deshaking_image_viewer.set_field_visible(self.model.use_overlay)
        self.deshaking_image_viewer.set_grid(self.model.use_grid)

        # clip image
        if self.model.use_perspective_correction:
            mat = self.model.perspective_points.get_transform_matrix() @ mat
        corrected_frame = cv2.warpPerspective(frame, mat, (frame.shape[1], frame.shape[0]), flags=cv2.INTER_AREA)
        if self.model.clip.is_none():
            self.model.clip.init(0, 0, frame.shape[1], frame.shape[0])
        self.clip_image_viewer.set_image(corrected_frame)
        self.clip_image_viewer.set_grid(self.model.use_grid)

    def __make_setting_file_path(self):
        path = get_path(self.input_file_picker.GetPath())
        if not path_exists(path):
            return None
        return path.with_suffix(SETTING_EXTENSION)

    def __update_model(self):
        self.model.select_sample_frame = self.sample_frame_button.GetValue()
        self.model.use_deshake_correction = self.use_deshake_correction_button.GetValue()
        self.model.use_rotation_correction = self.use_rotation_correction_button.GetValue()
        self.model.use_perspective_correction = self.use_perspective_correction_button.GetValue()
        self.model.use_overlay = self.use_overlay_button.GetValue()
        self.model.use_nega = self.use_nega_button.GetValue()
        self.model.use_grid = self.use_grid_button.GetValue()
        self.model.rotation_angle = get_spin_ctrl_value(self.rotation)

    def __save_setting(self):
        self.__update_model()
        path = self.__make_setting_file_path()
        if not path:
            return
        with open(path, 'w') as f:
            f.write(self.model.model_dump_json(indent=2))

    def __load_setting(self):
        path = self.__make_setting_file_path()
        if not path_exists(path):
            return
        def _g(value, default_value):
            if type(value) == float:
                return f'{value:.2f}'
            return value
        try:
            with open(path, 'r') as f:
                model = CorrectionDataModel.model_validate_json(f.read())
                self.model.copy_from(model)
                self.use_deshake_correction_button.SetValue(self.model.use_deshake_correction)
                self.use_rotation_correction_button.SetValue(self.model.use_rotation_correction)
                self.use_perspective_correction_button.SetValue(self.model.use_perspective_correction)
                self.use_overlay_button.SetValue(self.model.use_overlay)
                self.use_nega_button.SetValue(self.model.use_nega)
                self.use_grid_button.SetValue(self.model.use_grid)
                self.rotation.SetValue(_g(self.model.rotation_angle, '0.00'))
                if self.model.select_sample_frame:
                    self.sample_frame_button.SetValue(True)
                else:
                    self.base_frame_button.SetValue(True)
                self.deshaking_image_viewer.set_grid(self.model.use_grid)
        except Exception as e:
            wx.MessageBox(f'設定の読み込みに失敗しました:\n{e}', TOOL_NAME, wx.OK|wx.ICON_ERROR)

    def __load_image_catalog(self):
        path = get_path(self.input_file_picker.GetPath())
        if not path_exists(path):
            return
        self.model.clear()
        self.input_video_thumbnail.clear()
        self.base_image_viewer.clear()
        self.deshaking_image_viewer.clear()
        self.clip_image_viewer.clear()
        self.use_deshake_correction_button.SetValue(self.model.use_deshake_correction)
        self.use_rotation_correction_button.SetValue(self.model.use_rotation_correction)
        self.use_perspective_correction_button.SetValue(self.model.use_perspective_correction)
        self.use_overlay_button.SetValue(self.model.use_overlay)
        self.use_nega_button.SetValue(self.model.use_nega)
        self.use_grid_button.SetValue(self.model.use_grid)
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
        elif self.base_frame_button.GetValue():
            self.input_video_thumbnail.set_frame_position(self.model.base_frame_pos)
        if self.model.sample_frame_pos is None or self.model.sample_frame_pos >= count:
            self.model.sample_frame_pos = position
        elif self.sample_frame_button.GetValue():
            self.input_video_thumbnail.set_frame_position(self.model.sample_frame_pos)
        self.__set_base_image_viewer()
        self.__set_sample_image_viewer()
        self.Refresh()
        event.Skip()

    def __on_video_position_changed(self, event):
        if self.base_frame_button.GetValue():
            self.model.base_frame_pos = event.position
            self.__set_base_image_viewer()
            self.__set_sample_image_viewer()
        elif self.sample_frame_button.GetValue():
            self.model.sample_frame_pos = event.position
            self.__set_sample_image_viewer()
        event.Skip()

    def __on_base_frame_button_clicked(self, event):
        count = self.input_video_thumbnail.get_frame_count()
        if self.model.base_frame_pos is None or self.model.base_frame_pos >= count:
            return
        self.input_video_thumbnail.set_frame_position(self.model.base_frame_pos)
        self.model.select_sample_frame = False

    def __on_sample_frame_button_clicked(self, event):
        count = self.input_video_thumbnail.get_frame_count()
        if self.model.sample_frame_pos is None or self.model.sample_frame_pos >= count:
            return
        self.input_video_thumbnail.set_frame_position(self.model.sample_frame_pos)
        self.model.select_sample_frame = True

    def __on_field_added(self, event):
        self.model.shaking_detection_fields.append(event.field)
        self.setting_changed_time = time.time()
        self.__set_sample_image_viewer()
        self.base_image_viewer.Refresh()

    def __on_field_deleted(self, event):
        self.model.shaking_detection_fields.remove(event.field)
        self.setting_changed_time = time.time()
        self.__set_sample_image_viewer()
        self.base_image_viewer.Refresh()

    def __on_perspective_points_changed(self, event):
        self.__set_sample_image_viewer()

    def __on_clip_rect_changed(self, event):
        self.__set_sample_image_viewer()

    def __on_input_value_changed(self, event):
        self.setting_changed_time = time.time()
        event.Skip()

    def __on_setting_timer(self, event):
        if self.setting_changed_time is None:
            event.Skip()
            return
        if time.time() - self.setting_changed_time >= 1.0:
            self.setting_changed_time = None
            self.__update_model()
            self.__set_sample_image_viewer()
        event.Skip()

    def __on_close(self, event):
        self.setting_timer.Stop()
        self.__save_setting()
        event.Skip()

    def on_save_menu(self, event):
        super().on_save_menu(event)
        self.__save_setting()

    def __on_save_button_clicked(self, event):
        if self.input_video_thumbnail.get_frame_count() == 0:
            wx.MessageBox('連続画像が読み込まれていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return

        input_path = get_path(self.input_file_picker.GetPath())
        output_filename = input_path.stem.removesuffix(PNG_SUFFIX).removesuffix(TIFF_SUFFIX) + CORR_SUFFIX + '.txt'

        with wx.FileDialog(
            self, 
            '保存先の連続画像のカタログファイル名を入力してください。(連続画像のディレクトリ名にもなります)', 
            defaultDir=str(input_path.parent),
            defaultFile=output_filename,
            wildcard=IMAGE_CATALOG_FILE_WILDCARD,
            style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            self.__save_setting()
            output_path = get_path(fileDialog.GetPath())
            self.output_filename_text.SetValue(str(output_path))
            self.output_video_thumbnail.load_image_catalog(input_path, self.model, output_path)
        event.Skip()

    def __on_folder_button_clicked(self, event):
        path = get_path(self.output_filename_text.GetValue())
        if not path_exists(path):
            event.Skip()
            return
        wx.LaunchDefaultApplication(str(path.parent))
        event.Skip()
