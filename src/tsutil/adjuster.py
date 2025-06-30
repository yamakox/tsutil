import wx
import wx.adv
from pathlib import Path
from pydantic import BaseModel
from PIL import Image
import cv2
from .common import *
from .tool_frame import ToolFrame
from .components.image_viewer import ImageViewer, SCROLL_BAR_SIZE, EVT_MOUSE_OVER_IMAGE, EVT_MOUSE_CLICK_IMAGE
from .functions import unsharp_mask

# MARK: constants

MARGIN = 12
THUMBNAIL_HEIGHT = 100
THUMBNAIL_SIZE = (1000, THUMBNAIL_HEIGHT + SCROLL_BAR_SIZE)
PREVIEW_SIZE = (500, 300)
POSITION_LIST_SIZE = (300, 250)
ADJUST_SUFFIX = '_adjust'
TOOL_NAME = 'ステッチング画像の縦横比の調整'
ID_Y_TOP = 30001
ID_Y_BOTTOM = 30002
ID_POSITION_LIST = 30003
DEFAULT_PREVIEW_MESSAGE = '屋根Y・足元Y・列車の調整位置を選択して画像の該当場所をクリックすると座標が入力されます。'

class Position(BaseModel):
    length: int = 0
    description: str = '車両の位置'

class MeasurementData(BaseModel):
    height: int = 0
    factor: float = 0.95
    positions: list[Position] = []

def M(height: int, factor: float, positions: list[tuple[int, str]]):
    return MeasurementData(
        height=height, 
        positions=[Position(length=i[0], description=i[1]) for i in positions], 
    )

MEASUREMENT_DATASET = {
    '700系E編成': M(
        height=3650, 
        factor=0.95, 
        positions=[
            (0, '1両目のノーズ先端'), 
            (9200, '1両目のノーズ終端'), 
            (27350-9200, '1両目と2両目の間'), 
            (25000, '2両目と3両目の間'), 
            (25000, '3両目と4両目の間'), 
            (25000, '4両目と5両目の間'), 
            (25000, '5両目と6両目の間'), 
            (25000, '6両目と7両目の間'), 
            (25000, '7両目と8両目の間'), 
            (27350-9200, '8両目のノーズ終端'),
            (9200, '8両目のノーズ先端'), 
        ]
    ), 
    'ドクターイエロー': M(
        height=3650, 
        factor=0.95, 
        positions=[
            (0, '1両目のノーズ先端'), 
            (9200, '1両目のノーズ終端'), 
            (27350-9200, '1両目と2両目の間'), 
            (25000, '2両目と3両目の間'), 
            (25000, '3両目と4両目の間'), 
            (25000, '4両目と5両目の間'), 
            (25000, '5両目と6両目の間'), 
            (25000, '6両目と7両目の間'), 
            (27350-9200, '7両目のノーズ終端'),
            (9200, '7両目のノーズ先端'), 
        ]
    ), 
}

# MARK: main window

class MainFrame(ToolFrame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=TOOL_NAME, *args, **kw)
        self.file_menu_save.Enable(False)
        self.raw_image = None
        self.thumb_image = None
        self.raw_image_x = None
        self.thumb_ratio = None
        self.last_focus = None
        self.positions = []

        frame_sizer = wx.GridSizer(rows=1, cols=1, gap=wx.Size(0, 0))
        panel = wx.Panel(self)
        sizer = wx.FlexGridSizer(rows=0, cols=1, gap=wx.Size(0, 0))
        sizer.AddGrowableCol(0)
        row = 0

        # input file panel
        input_file_panel = wx.Panel(panel)
        input_file_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        input_file_sizer.AddGrowableCol(1)
        input_file_sizer.Add(wx.StaticText(input_file_panel, label='調整するステッチング画像ファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.input_file_picker = wx.FilePickerCtrl(
            input_file_panel,
            message='ステッチング画像ファイルを選択してください。',
            wildcard=IMAGE_FILE_WILDCARD,
            style=wx.FLP_OPEN|wx.FLP_USE_TEXTCTRL|wx.FLP_FILE_MUST_EXIST,
        )
        self.input_file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self.__on_input_file_changed)
        input_file_sizer.Add(self.input_file_picker, flag=wx.EXPAND)
        input_file_panel.SetSizerAndFit(input_file_sizer)
        sizer.Add(input_file_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # input image thumbnail
        sizer.Add(wx.StaticText(panel, label='ステッチング画像の任意の場所をクリックすると、拡大画像が下に表示されます。'), flag=wx.ALIGN_CENTER)
        self.input_image_thumbnail = ImageViewer(panel, min_size=THUMBNAIL_SIZE, enable_zoom=False)
        sizer.Add(self.input_image_thumbnail, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 2

        # setting panel
        setting_panel = self.__make_setting_panel(panel)
        sizer.Add(setting_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        sizer.AddGrowableRow(row)
        row += 1

        # save button
        save_button = wx.Button(panel, label='調整したステッチング画像を保存する...')
        save_button.Bind(wx.EVT_BUTTON, self.__on_save_button_clicked)
        sizer.Add(save_button, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 1

        # output image thumbnail
        self.output_image_thumbnail = ImageViewer(panel, min_size=THUMBNAIL_SIZE, enable_zoom=False)
        sizer.Add(self.output_image_thumbnail, flag=wx.ALIGN_CENTER)
        row += 1

        # output file panel
        output_file_panel = wx.Panel(panel)
        output_file_sizer = wx.FlexGridSizer(cols=3, gap=wx.Size(MARGIN, 0))
        output_file_sizer.AddGrowableCol(1)
        output_file_sizer.Add(wx.StaticText(output_file_panel, label='調整後のステッチング画像ファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.output_filename_text = wx.TextCtrl(output_file_panel, value='', style=wx.TE_READONLY)
        output_file_sizer.Add(self.output_filename_text, flag=wx.EXPAND)
        folder_button = wx.Button(output_file_panel, label='フォルダを開く')
        folder_button.Bind(wx.EVT_BUTTON, self.__on_folder_button_clicked)
        output_file_sizer.Add(folder_button, flag=wx.ALIGN_CENTER_VERTICAL)
        output_file_panel.SetSizerAndFit(output_file_sizer)
        sizer.Add(output_file_panel, flag=wx.EXPAND|wx.TOP, border=MARGIN)
        row += 1

        panel.SetSizer(sizer)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=16)
        self.SetSizerAndFit(frame_sizer)

        self.input_image_thumbnail.Bind(EVT_MOUSE_CLICK_IMAGE, self.__on_mouse_click_thumbnail)

    def __make_setting_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        sizer.AddGrowableRow(0)
        sizer.AddGrowableCol(1)

        setting_panel = wx.Panel(panel)
        setting_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 8))
        row = 0

        selector_panel = wx.Panel(setting_panel)
        selector_sizer = wx.GridSizer(rows=2, cols=1, gap=wx.Size(0, 2))
        selector_sizer.Add(wx.StaticText(selector_panel, label='列車の種類を選択してください:', style=wx.ALIGN_LEFT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.selector = wx.Choice(selector_panel)
        self.selector.Append(list(MEASUREMENT_DATASET.keys()))
        self.selector.SetSelection(wx.NOT_FOUND)
        self.selector.Bind(wx.EVT_CHOICE, self.__on_selector_choice)
        selector_sizer.Add(self.selector, flag=wx.EXPAND)
        selector_panel.SetSizerAndFit(selector_sizer)
        setting_sizer.Add(selector_panel, flag=wx.EXPAND)
        row += 1

        height_panel = wx.Panel(setting_panel)
        height_sizer = wx.GridSizer(rows=2, cols=4, gap=wx.Size(0, 4))
        height_sizer.Add(wx.StaticText(height_panel, label='屋根Y:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.y_top = wx.SpinCtrl(height_panel, id=ID_Y_TOP, name='y_top', value="0", min=0, max=10000, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        self.y_top.Bind(wx.EVT_SET_FOCUS, self.__on_set_focus)
        height_sizer.Add(self.y_top, flag=wx.EXPAND|wx.LEFT, border=MARGIN)
        height_sizer.Add(wx.StaticText(height_panel, label='足元Y:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.y_bottom = wx.SpinCtrl(height_panel, id=ID_Y_BOTTOM, name='y_bottom', value="3840", min=0, max=10000, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        self.y_bottom.Bind(wx.EVT_SET_FOCUS, self.__on_set_focus)
        height_sizer.Add(self.y_bottom, flag=wx.EXPAND|wx.LEFT, border=MARGIN)
        height_sizer.Add(wx.StaticText(height_panel, label='補正係数:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.factor = wx.SpinCtrlDouble(height_panel, name='factor', value="1.00", min=0.1, max=2.0, inc=0.01, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        height_sizer.Add(self.factor, flag=wx.EXPAND|wx.LEFT, border=MARGIN)
        height_sizer.Add(wx.StaticText(height_panel, label='左右余白:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.space = wx.SpinCtrl(height_panel, name='space', value="1000", min=0, max=10000, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        height_sizer.Add(self.space, flag=wx.EXPAND|wx.LEFT, border=MARGIN)
        height_panel.SetSizerAndFit(height_sizer)
        setting_sizer.Add(height_panel, flag=wx.EXPAND)
        row += 1

        self.position_list = wx.ListCtrl(setting_panel, id=ID_POSITION_LIST, name='position_list', size=parent.FromDIP(wx.Size(*POSITION_LIST_SIZE)), style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.position_list.InsertColumn(0, '列車の調整位置', wx.LIST_FORMAT_LEFT, width=200)
        self.position_list.InsertColumn(1, 'X座標', wx.LIST_FORMAT_RIGHT, width=100)
        self.position_list.Bind(wx.EVT_SET_FOCUS, self.__on_set_focus)
        self.position_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.__on_set_focus)
        self.position_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.__on_set_focus)
        setting_sizer.Add(self.position_list, flag=wx.EXPAND)
        setting_sizer.AddGrowableRow(row)
        row += 1

        option_panel = wx.Panel(setting_panel)
        option_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(0, 4))
        option_sizer.AddGrowableCol(0)
        option_sizer.Add(wx.StaticText(option_panel, label='アンシャープマスクの適用 (0.0: 適用しない):', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.unsharp_mask_parameter = wx.SpinCtrlDouble(option_panel, value="1.5", min=0.0, max=10.0, inc=0.1, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        option_sizer.Add(self.unsharp_mask_parameter, flag=wx.EXPAND|wx.LEFT, border=MARGIN)
        option_panel.SetSizerAndFit(option_sizer)
        setting_sizer.Add(option_panel, flag=wx.EXPAND)
        row += 1

        setting_panel.SetSizerAndFit(setting_sizer)
        sizer.Add(setting_panel, flag=wx.EXPAND)

        preview_panel = wx.Panel(panel)
        preview_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        preview_sizer.AddGrowableRow(1)
        preview_sizer.AddGrowableCol(0)

        self.preview_message = wx.StaticText(preview_panel, label=DEFAULT_PREVIEW_MESSAGE, style=wx.ALIGN_CENTER)
        preview_sizer.Add(self.preview_message, flag=wx.EXPAND)

        self.previewer = ImageViewer(preview_panel, min_size=PREVIEW_SIZE)
        self.previewer.set_grid(True, True)
        self.previewer.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        self.previewer.Bind(EVT_MOUSE_OVER_IMAGE, self.__on_mouse_over_preview)
        self.previewer.Bind(EVT_MOUSE_CLICK_IMAGE, self.__on_mouse_click_preview)
        preview_sizer.Add(self.previewer, flag=wx.EXPAND)

        info_panel = wx.Panel(preview_panel)
        info_sizer = wx.FlexGridSizer(rows=1, cols=6, gap=wx.Size(0, 0))
        info_sizer.AddGrowableCol(0, proportion=1)
        info_sizer.AddGrowableCol(1, proportion=10)
        info_sizer.AddGrowableCol(2, proportion=16)
        info_sizer.AddGrowableCol(3, proportion=1)
        info_sizer.AddGrowableCol(4, proportion=10)
        info_sizer.AddGrowableCol(5, proportion=16)
        info_sizer.Add(wx.StaticText(info_panel, label='X:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.info_x = wx.StaticText(info_panel, label='', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE)
        info_sizer.Add(self.info_x, flag=wx.EXPAND|wx.LEFT, border=8)
        info_sizer.AddStretchSpacer()
        info_sizer.Add(wx.StaticText(info_panel, label='Y:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.info_y = wx.StaticText(info_panel, label='', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE)
        info_sizer.Add(self.info_y, flag=wx.EXPAND|wx.LEFT, border=8)
        info_sizer.AddStretchSpacer()
        info_panel.SetSizerAndFit(info_sizer)
        preview_sizer.Add(info_panel, flag=wx.EXPAND)

        preview_panel.SetSizerAndFit(preview_sizer)
        sizer.Add(preview_panel, flag=wx.EXPAND)

        panel.SetSizerAndFit(sizer)
        return panel

    def __clear(self):
        self.raw_image = None
        self.raw_image_x = None
        self.thumb_ratio = None
        self.last_focus = None
        self.positions.clear()
        self.input_image_thumbnail.clear()
        self.output_image_thumbnail.clear()
        self.output_filename_text.SetValue('')
        self.previewer.clear()
        self.info_x.SetLabel('')
        self.info_y.SetLabel('')
        self.selector.SetSelection(wx.NOT_FOUND)
        self.y_top.SetValue(0)
        self.y_bottom.SetValue(3840)
        self.factor.SetValue('1.00')
        self.space.SetValue(1000)
        self.position_list.DeleteAllItems()
        self.preview_message.SetLabel(DEFAULT_PREVIEW_MESSAGE)

    def __update_position_list(self, row_index=None):
        selector_index = self.selector.GetSelection()
        if selector_index == wx.NOT_FOUND:
            self.position_list.DeleteAllItems()
            return
        key = self.selector.GetString(selector_index)
        data = MEASUREMENT_DATASET[key]
        if row_index is None:
            self.position_list.DeleteAllItems()
            for entry, position in zip(data.positions, self.positions):
                self.position_list.Append([
                    entry.description, 
                    str(position) if position is not None else ''
                ])
        else:
            self.position_list.SetItem(
                row_index, 
                1, 
                str(self.positions[row_index]) if self.positions[row_index] is not None else ''
            )

    def __show_preview(self, image_x):
        s = self.raw_image.shape[0]
        self.raw_image_x = min(max(s, image_x), self.raw_image.shape[1] - s)
        self.previewer.clear()
        x0 = self.raw_image_x - s
        x1 = x0 + s * 2
        self.previewer.set_image(self.raw_image[:, x0:x1, :])

    def __adjust_image(self):
        index = self.selector.GetSelection()
        if self.raw_image is None or index == wx.NOT_FOUND or not self.positions or None in self.positions:
            raise Exception('画像調整に必要なデータがありません。')
        key = self.selector.GetString(index)
        data = MEASUREMENT_DATASET[key]
        
        car_height = data.height * get_spin_ctrl_value(self.factor)
        if car_height <= 0:
            raise Exception('補正係数が正しくありません。')
        car_widths = np.array([i.length for i in data.positions[1:]])

        y_src_top = get_spin_ctrl_value(self.y_top)
        y_src_bottom = get_spin_ctrl_value(self.y_bottom)
        if y_src_bottom <= y_src_top:
            raise Exception('屋根のY座標が足元のY座標より下にあります。')
        h, w = self.raw_image.shape[:2]
        dst_height = h
        dst_widths = (car_widths * (y_src_bottom - y_src_top) / car_height + .5).astype(int)
        dst_width = dst_widths.sum()
        src_widths = np.array([x2 - x1 for (x1, x2) in zip(self.positions[:-1], self.positions[1:])])
        if min(src_widths) <= 0:
            raise Exception('調整位置のX座標は上から小→大(画像の左→右)の順で入力してください。')
        max_ratio = np.max(dst_widths / src_widths)
        if max_ratio > 1:
            # 補正後の幅が元画像より大きいと拡大してしまうため、高さを縮めて拡大しないようにする
            dst_height = int(h / max_ratio) & ~1
            img = cv2.resize(self.raw_image, (self.raw_image.shape[1], dst_height), interpolation=cv2.INTER_AREA)
            dst_widths = (dst_widths / max_ratio + .5).astype(int)
            dst_width = dst_widths.sum()
        else:
            img = self.raw_image
        margin = get_spin_ctrl_value(self.space)
        dst_width += margin * 2

        logger.debug(f'resize from {w}x{h} to {dst_width}x{dst_height}')

        buf = np.zeros((dst_height, dst_width, 3), dtype=np.uint8)
        if self.positions[0] < margin or img.shape[1] - self.positions[-1] < margin:
            max_space = min(self.positions[0], img.shape[1] - self.positions[-1])
            raise Exception('余白を{max_space}以下にしてください。')
        buf[:, :margin, :] = img[:, self.positions[0]-margin:self.positions[0], :]
        x = margin
        for i, dw in enumerate(dst_widths):
            x1 = x + dw
            buf[:, x:x1, :] = cv2.resize(
                img[:, self.positions[i]:self.positions[i+1], :], 
                (dw, dst_height), 
                interpolation=cv2.INTER_AREA
            )
            x = x1
        buf[:, x:, :] = img[:, self.positions[-1]:self.positions[-1]+margin, :]
        unsharp_mask_parameter = get_spin_ctrl_value(self.unsharp_mask_parameter)
        if unsharp_mask_parameter > 0.0:
            buf = unsharp_mask(buf, unsharp_mask_parameter)
        return buf

    def __on_input_file_changed(self, event):
        path = get_path(self.input_file_picker.GetPath())
        if not path_exists(path):
            event.Skip()
            return
        self.__clear()
        self.raw_image = cv2.cvtColor(cv2.imread(str(path), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB)
        self.thumb_ratio = THUMBNAIL_HEIGHT / self.raw_image.shape[0]
        self.thumb_image = cv2.resize(self.raw_image, (int(self.raw_image.shape[1] * self.thumb_ratio), THUMBNAIL_HEIGHT), interpolation=cv2.INTER_AREA)
        self.input_image_thumbnail.set_image(self.thumb_image)
        self.input_image_thumbnail.set_image_zoom_position(0, THUMBNAIL_HEIGHT//2, 1.0)
        self.y_top.SetValue(0)
        self.y_bottom.SetValue(self.raw_image.shape[0])
        event.Skip()

    def __on_mouse_click_thumbnail(self, event):
        x = int(event.image_x / self.thumb_ratio + .5)
        self.__show_preview(x)
        event.Skip()

    def __on_mouse_over_preview(self, event):
        x, y = event.image_x, event.image_y
        if x is None:
            self.info_x.SetLabel('')
            self.info_y.SetLabel('')
        else:
            s = self.raw_image.shape[0]
            x += self.raw_image_x - s
            self.info_x.SetLabel(f'{x}/{self.raw_image.shape[1]}')
            self.info_y.SetLabel(f'{y}/{self.raw_image.shape[0]}')
        event.Skip()

    def __on_mouse_click_preview(self, event):
        x, y = event.image_x, event.image_y
        if self.last_focus == ID_Y_TOP:
            self.y_top.SetValue(y)
        elif self.last_focus == ID_Y_BOTTOM:
            self.y_bottom.SetValue(y)
        elif self.last_focus == ID_POSITION_LIST:
            index = self.position_list.GetFirstSelected()
            if index > -1:
                s = self.raw_image.shape[0]
                self.positions[index] = x + self.raw_image_x - s
                self.__update_position_list(index)
                self.position_list.Select(index, 0)
        self.last_focus = None
        self.preview_message.SetLabel(DEFAULT_PREVIEW_MESSAGE)
        event.Skip()

    def __on_selector_choice(self, event):
        index = self.selector.GetSelection()
        if index != wx.NOT_FOUND:
            key = self.selector.GetString(index)
            data = MEASUREMENT_DATASET[key]
            self.positions = [None] * len(data.positions)
            self.factor.SetValue(f'{data.factor:.2f}')
            self.__update_position_list()
        event.Skip()

    def __on_set_focus(self, event):
        if self.raw_image is None:
            return
        self.last_focus = event.Id
        if self.last_focus == ID_Y_TOP:
            self.preview_message.SetLabel('画像をクリックして、屋根のY座標を決定してください。')
            event.Skip()
            return
        elif self.last_focus == ID_Y_BOTTOM:
            self.preview_message.SetLabel('画像をクリックして、足元のY座標を決定してください。')
            event.Skip()
            return
        elif self.last_focus == ID_POSITION_LIST:
            index = self.position_list.GetFirstSelected()
            if index > -1:
                text = self.position_list.GetItemText(index, 0)
                self.preview_message.SetLabel(f'画像をクリックして、{text}を決定してください。')
                if self.positions[index] is not None:
                    self.__show_preview(self.positions[index])
                event.Skip()
                return
        self.preview_message.SetLabel(DEFAULT_PREVIEW_MESSAGE)
        event.Skip()

    def __on_save_button_clicked(self, event):
        if self.raw_image is None:
            wx.MessageBox('ステッチング画像が読み込まれていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return
        if  not self.positions or None in self.positions:
            wx.MessageBox('調整位置の座標が設定されていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return

        input_path = get_path(self.input_file_picker.GetPath())
        output_filename = input_path.stem + ADJUST_SUFFIX + input_path.suffix

        with wx.FileDialog(
            self, 
            '調整したステッチング画像の保存先ファイル名を入力してください。', 
            defaultDir=str(input_path.parent),
            defaultFile=output_filename,
            wildcard=IMAGE_FILE_WILDCARD,
            style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            output_path = get_path(fileDialog.GetPath())
            self.output_filename_text.SetValue(str(output_path))
            try:
                buf = self.__adjust_image()
                cv2.imwrite(str(output_path), cv2.cvtColor(buf, cv2.COLOR_RGB2BGR))
                self.output_image_thumbnail.set_image(cv2.resize(buf, (int(buf.shape[1] * THUMBNAIL_HEIGHT / buf.shape[0]), THUMBNAIL_HEIGHT), interpolation=cv2.INTER_AREA))
                self.output_image_thumbnail.set_image_zoom_position(0, THUMBNAIL_HEIGHT//2, 1.0)
            except Exception as excep:
                wx.MessageBox(str(excep), 'エラー', wx.OK|wx.ICON_ERROR)
        event.Skip()

    def __on_folder_button_clicked(self, event):
        path = get_path(self.output_filename_text.GetValue())
        if not path_exists(path):
            event.Skip()
            return
        wx.LaunchDefaultApplication(str(path.parent))
        event.Skip()
