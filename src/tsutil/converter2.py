import wx
import wx.adv
from pydantic import BaseModel
import cv2
import time
import threading
from ffio import FrameWriter
from .common import *
from .tool_frame import ToolFrame
from .components.range_image_viewer import RangeImageViewer, EVT_FIELD_SELECTED
from .components.image_viewer import ImageViewer, SCROLL_BAR_SIZE, EVT_MOUSE_OVER_IMAGE, EVT_MOUSE_CLICK_IMAGE
from .functions import sigmoid_space

# MARK: constants

MARGIN = 12
THUMBNAIL_HEIGHT = 100
THUMBNAIL_SIZE = (1000, THUMBNAIL_HEIGHT + SCROLL_BAR_SIZE)
PREVIEW_SIZE = (480 + SCROLL_BAR_SIZE, 270 + SCROLL_BAR_SIZE)
SEQUENCE_LIST_SIZE = (300, 250)
TOOL_NAME = 'ステッチング画像から動画に変換'
SEQUENCE_SUFFIX = '_sequence.json'
SEQUENCE_FILE_WILDCARD = 'JSON files (*.json)|*.json'
MOVIE_SIZE = (1280, 720)
FPS = 60

class Accel(BaseModel):
    value: float = 0
    description: str = ''

ACCELS = [
    Accel(value=-8, description='低'), 
    Accel(value=-5, description='中'), 
    Accel(value=-2, description='高'), 
    Accel(value=0, description='最大'), 
]
DECELS = [
    Accel(value=8, description='低'), 
    Accel(value=5, description='中'), 
    Accel(value=2, description='高'), 
    Accel(value=0, description='最大'), 
]

ACCELS_MAP = {i.value:i for i in ACCELS}
DECELS_MAP = {i.value:i for i in DECELS}

def find_accel_index(accel_list: list[Accel], value: float):
    for i, item in enumerate(accel_list):
        if item.value == value:
            return i
    return None

# models

class SequenceItem(BaseModel):
    x: int = 0
    y: int = 0
    w: int = 0
    init_v: float = 0
    final_v: float = 0
    trans_t: float = 3.0
    still_t: float = 2.0

    def set_values(self, x, y, w, init_v, final_v, trans_t, still_t):
        self.x = x
        self.y = y
        self.w = w
        self.init_v = init_v
        self.final_v = final_v
        self.trans_t = trans_t
        self.still_t = still_t

class SequenceModel(BaseModel):
    items: list[SequenceItem] = []

# MARK: events

myEVT_MOVIE_SAVING = wx.NewEventType()
EVT_MOVIE_SAVING = wx.PyEventBinder(myEVT_MOVIE_SAVING)

class MovieSavingEvent(wx.ThreadEvent):
    def __init__(self, current, total):
        super().__init__(myEVT_MOVIE_SAVING)
        self.current = current
        self.total = total

# MARK: main window

class MainFrame(ToolFrame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=TOOL_NAME, *args, **kw)
        self.raw_image = None
        self.raw_image_x = None
        self.raw_image_y = None
        self.raw_image_w = None
        self.thumb_image = None
        self.thumb_ratio = None
        self.sequence = SequenceModel()
        self.buf = np.zeros((MOVIE_SIZE[1], MOVIE_SIZE[0], 3), dtype=np.uint8)
        self.saving = None

        frame_sizer = wx.GridSizer(rows=1, cols=1, gap=wx.Size(0, 0))
        panel = wx.Panel(self)
        sizer = wx.FlexGridSizer(rows=0, cols=1, gap=wx.Size(0, 0))
        sizer.AddGrowableCol(0)
        row = 0

        # input file panel
        input_file_panel = wx.Panel(panel)
        input_file_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        input_file_sizer.AddGrowableCol(1)
        input_file_sizer.Add(wx.StaticText(input_file_panel, label='動画にするステッチング画像ファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
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
        sizer.Add(wx.StaticText(panel, label='ステッチング画像の任意の場所をドラッグで選択して、動画で表示したい場所をリストに追加してください。'), flag=wx.ALIGN_CENTER)
        self.input_image_thumbnail = RangeImageViewer(panel, min_size=THUMBNAIL_SIZE, enable_zoom=True)
        sizer.Add(self.input_image_thumbnail, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 2

        # setting panel
        setting_panel = self.__make_setting_panel(panel)
        sizer.Add(setting_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        sizer.AddGrowableRow(row)
        row += 1

        # save button
        start_button = wx.Button(panel, label='ステッチング画像から動画に変換する...')
        start_button.Bind(wx.EVT_BUTTON, self.__on_start_button_clicked)
        sizer.Add(start_button, flag=wx.ALIGN_CENTER|wx.TOP, border=MARGIN)
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

        self.setting_changed_time = None
        self.setting_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.__on_setting_timer)
        self.setting_timer.Start(100)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=16)
        self.SetSizerAndFit(frame_sizer)

        self.input_image_thumbnail.Bind(EVT_FIELD_SELECTED, self.__on_field_selected)
        self.Bind(EVT_MOVIE_SAVING, self.__on_movie_saving)
        self.Bind(wx.EVT_CLOSE, self.__on_close)

    def __make_setting_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        sizer.AddGrowableRow(0)
        sizer.AddGrowableCol(1)

        preview_panel = wx.Panel(panel)
        preview_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        preview_sizer.AddGrowableCol(0)
        preview_sizer.Add(wx.StaticText(preview_panel, label='動画で表示したい場所:', style=wx.ALIGN_LEFT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        row = 1

        self.previewer = ImageViewer(preview_panel, min_size=PREVIEW_SIZE)
        self.previewer.set_grid(True, True)
        self.previewer.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        self.previewer.Bind(EVT_MOUSE_OVER_IMAGE, self.__on_mouse_over_preview)
        preview_sizer.Add(self.previewer, flag=wx.ALIGN_CENTER)
        row += 1

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
        preview_sizer.Add(info_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        option1_panel = wx.Panel(preview_panel)
        option1_sizer = wx.FlexGridSizer(cols=6, gap=wx.Size(4, 0))
        [option1_sizer.AddGrowableCol(i) for i in [1, 3, 5]]
        option1_sizer.Add(wx.StaticText(option1_panel, label='中心X:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.seq_x = wx.SpinCtrl(option1_panel, value="0", min=0, max=1000000, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        self.seq_x.Bind(wx.EVT_TEXT, self.__on_input_value_changed)
        self.seq_x.Bind(wx.EVT_SPINCTRL, self.__on_input_value_changed)
        option1_sizer.Add(self.seq_x, flag=wx.EXPAND|wx.RIGHT, border=8)
        option1_sizer.Add(wx.StaticText(option1_panel, label='中心Y:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.seq_y = wx.SpinCtrl(option1_panel, value="0", min=0, max=10000, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        self.seq_y.Bind(wx.EVT_TEXT, self.__on_input_value_changed)
        self.seq_y.Bind(wx.EVT_SPINCTRL, self.__on_input_value_changed)
        option1_sizer.Add(self.seq_y, flag=wx.EXPAND|wx.RIGHT, border=8)
        option1_sizer.Add(wx.StaticText(option1_panel, label='幅:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.seq_w = wx.SpinCtrl(option1_panel, value="0", min=0, max=1000000, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        self.seq_w.Bind(wx.EVT_TEXT, self.__on_input_value_changed)
        self.seq_w.Bind(wx.EVT_SPINCTRL, self.__on_input_value_changed)
        option1_sizer.Add(self.seq_w, flag=wx.EXPAND|wx.RIGHT, border=8)
        option1_panel.SetSizerAndFit(option1_sizer)
        preview_sizer.Add(option1_panel, flag=wx.ALIGN_LEFT|wx.BOTTOM, border=MARGIN)
        row += 1

        option2_panel = wx.Panel(preview_panel)
        option2_sizer = wx.FlexGridSizer(cols=8, gap=wx.Size(4, 0))
        option2_sizer.Add(wx.StaticText(option2_panel, label='初速:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.seq_init_v = wx.Choice(option2_panel)
        self.seq_init_v.Append([i.description for i in ACCELS])
        self.seq_init_v.SetSelection(0)
        option2_sizer.Add(self.seq_init_v, flag=wx.RIGHT, border=8)
        option2_sizer.Add(wx.StaticText(option2_panel, label='終速:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.seq_final_v = wx.Choice(option2_panel)
        self.seq_final_v.Append([i.description for i in ACCELS])
        self.seq_final_v.SetSelection(0)
        option2_sizer.Add(self.seq_final_v, flag=wx.RIGHT, border=8)
        option2_sizer.Add(wx.StaticText(option2_panel, label='遷移(秒):', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.seq_trans_t = wx.SpinCtrlDouble(option2_panel, value="3.0", min=0.0, max=100.0, inc=0.1, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        option2_sizer.Add(self.seq_trans_t, flag=wx.RIGHT, border=8)
        option2_sizer.Add(wx.StaticText(option2_panel, label='静止(秒):', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        self.seq_still_t = wx.SpinCtrlDouble(option2_panel, value="2.0", min=0.0, max=100.0, inc=0.1, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        option2_sizer.Add(self.seq_still_t, flag=wx.RIGHT, border=8)
        option2_panel.SetSizerAndFit(option2_sizer)
        preview_sizer.Add(option2_panel, flag=wx.ALIGN_LEFT)
        row += 1

        preview_panel.SetSizerAndFit(preview_sizer)
        sizer.Add(preview_panel, flag=wx.EXPAND)

        setting_panel = wx.Panel(panel)
        setting_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        setting_sizer.AddGrowableCol(0)
        setting_sizer.Add(wx.StaticText(setting_panel, label='動画で表示したい場所のリスト:', style=wx.ALIGN_LEFT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
        row = 1

        self.sequence_list = wx.ListCtrl(setting_panel, size=dpi_aware_size(parent, wx.Size(*SEQUENCE_LIST_SIZE)), style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.sequence_list.InsertColumn(0, '中心X', wx.LIST_FORMAT_RIGHT, width=dpi_aware(parent, 70))
        self.sequence_list.InsertColumn(1, '中心Y', wx.LIST_FORMAT_RIGHT, width=dpi_aware(parent, 70))
        self.sequence_list.InsertColumn(2, '幅', wx.LIST_FORMAT_RIGHT, width=dpi_aware(parent, 70))
        self.sequence_list.InsertColumn(3, '初速', wx.LIST_FORMAT_CENTER, width=dpi_aware(parent, 60))
        self.sequence_list.InsertColumn(4, '終速', wx.LIST_FORMAT_CENTER, width=dpi_aware(parent, 60))
        self.sequence_list.InsertColumn(5, '遷移(秒)', wx.LIST_FORMAT_RIGHT, width=dpi_aware(parent, 70))
        self.sequence_list.InsertColumn(6, '静止(秒)', wx.LIST_FORMAT_RIGHT, width=dpi_aware(parent, 70))
        self.sequence_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.__on_seq_list_item_selected)
        self.sequence_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.__on_seq_list_item_selected)
        self.sequence_list.Bind(wx.EVT_LIST_BEGIN_DRAG, self.__on_seq_list_begin_drag)
        self.sequence_list.SetDropTarget(ListDropTarget(self.__handle_drop))
        setting_sizer.Add(self.sequence_list, flag=wx.EXPAND|wx.BOTTOM, border=8)
        setting_sizer.AddGrowableRow(row)
        row += 1

        op_panel = wx.Panel(setting_panel)
        op_sizer = wx.GridSizer(cols=5, gap=wx.Size(6, 8))
        self.add_button = wx.Button(op_panel, label='追加')
        self.add_button.Bind(wx.EVT_BUTTON, self.__on_add_button_clicked)
        self.add_button.Enable(False)
        op_sizer.Add(self.add_button, flag=wx.EXPAND)
        self.change_button = wx.Button(op_panel, label='更新')
        self.change_button.Enable(False)
        self.change_button.Bind(wx.EVT_BUTTON, self.__on_change_button_clicked)
        op_sizer.Add(self.change_button, flag=wx.EXPAND)
        self.delete_button = wx.Button(op_panel, label='削除')
        self.delete_button.Enable(False)
        self.delete_button.Bind(wx.EVT_BUTTON, self.__on_delete_button_clicked)
        op_sizer.Add(self.delete_button, flag=wx.EXPAND)
        self.up_button = wx.Button(op_panel, label='上へ')
        self.up_button.Enable(False)
        self.up_button.Bind(wx.EVT_BUTTON, self.__on_up_button_clicked)
        op_sizer.Add(self.up_button, flag=wx.EXPAND)
        self.down_button = wx.Button(op_panel, label='下へ')
        self.down_button.Enable(False)
        self.down_button.Bind(wx.EVT_BUTTON, self.__on_down_button_clicked)
        op_sizer.Add(self.down_button, flag=wx.EXPAND)
        self.save_button = wx.Button(op_panel, label='セーブ')
        self.save_button.Enable(False)
        self.save_button.Bind(wx.EVT_BUTTON, self.__on_save_button_clicked)
        op_sizer.Add(self.save_button, flag=wx.EXPAND)
        self.load_button = wx.Button(op_panel, label='ロード')
        self.load_button.Enable(False)
        self.load_button.Bind(wx.EVT_BUTTON, self.__on_load_button_clicked)
        op_sizer.Add(self.load_button, flag=wx.EXPAND)
        op_panel.SetSizerAndFit(op_sizer)
        setting_sizer.Add(op_panel, flag=wx.ALIGN_CENTER)
        row += 1

        setting_panel.SetSizerAndFit(setting_sizer)
        sizer.Add(setting_panel, flag=wx.EXPAND)
        
        panel.SetSizerAndFit(sizer)
        return panel

    def __clear(self):
        self.raw_image = None
        self.raw_image_x = None
        self.raw_image_y = None
        self.raw_image_w = None
        self.thumb_image = None
        self.thumb_ratio = None
        self.sequence.items.clear()
        self.buf[...] = 0
        self.input_image_thumbnail.clear()
        self.output_filename_text.SetValue('')
        self.sequence_list.DeleteAllItems()
        self.add_button.Enable(False)
        self.change_button.Enable(False)
        self.delete_button.Enable(False)
        self.save_button.Enable(False)
        self.load_button.Enable(False)
        self.__clear_form(True)

    def __clear_form(self, init_max=False):
        if init_max:
            self.seq_x.SetMax(1000000)
            self.seq_y.SetMax(10000)
            self.seq_w.SetMax(1000000)
        self.seq_x.SetValue(0)
        self.seq_y.SetValue(0)
        self.seq_w.SetValue(0)
        self.seq_init_v.SetSelection(0)
        self.seq_final_v.SetSelection(0)
        self.seq_trans_t.SetValue(3.0)
        self.seq_still_t.SetValue(2.0)
        self.previewer.clear()
        self.info_x.SetLabel('')
        self.info_y.SetLabel('')
        self.add_button.Enable(False)
        self.change_button.Enable(False)
        self.delete_button.Enable(False)

    def __set_form(self, seq_item: SequenceItem):
        self.seq_x.SetValue(seq_item.x)
        self.seq_y.SetValue(seq_item.y)
        self.seq_w.SetValue(seq_item.w)
        self.raw_image_x = seq_item.x
        self.raw_image_y = seq_item.y
        self.raw_image_w = seq_item.w
        self.seq_init_v.SetSelection(find_accel_index(ACCELS, seq_item.init_v))
        self.seq_final_v.SetSelection(find_accel_index(DECELS, seq_item.final_v))
        self.seq_trans_t.SetValue(seq_item.trans_t)
        self.seq_still_t.SetValue(seq_item.still_t)
        self.__render_buf(seq_item.x, seq_item.y, seq_item.w)
        self.previewer.set_image(self.buf)

    def __update_sequence_list(self, visible_row_index=None):
        self.sequence_list.DeleteAllItems()
        for i, item in enumerate(self.sequence.items):
            if i > 0:
                self.sequence_list.Append([
                    str(item.x), 
                    str(item.y), 
                    str(item.w), 
                    ACCELS_MAP[item.init_v].description, 
                    DECELS_MAP[item.final_v].description, 
                    f'{item.trans_t:.1f}', 
                    f'{item.still_t:.1f}', 
                ])
            else:
                self.sequence_list.Append([
                    str(item.x), 
                    str(item.y), 
                    str(item.w), 
                    f'無効({ACCELS_MAP[item.init_v].description})', 
                    f'無効({DECELS_MAP[item.final_v].description})', 
                    f'無効({item.trans_t:.1f})', 
                    f'{item.still_t:.1f}', 
                ])
        if visible_row_index is not None:
            self.sequence_list.EnsureVisible(visible_row_index)
            self.sequence_list.Select(visible_row_index)
            self.__set_form(self.sequence.items[visible_row_index])
        self.save_button.Enable(len(self.sequence.items) > 0)

    def __render_buf(self, image_x, image_y, image_w):
        _r = self.buf.shape[1] / image_w
        if _r < self.thumb_ratio:
            _r = _r / self.thumb_ratio
            src = self.thumb_image
            image_x *= self.thumb_ratio
            image_y *= self.thumb_ratio
            image_w *= self.thumb_ratio
        else:
            src = self.raw_image
        _w = image_w / 2
        _h = int(_w * self.buf.shape[0] / self.buf.shape[1] + .5)
        img_x0, img_x1 = int(image_x - _w + .5), int(image_x + _w + .5)
        img_y0, img_y1 = int(image_y - _h + .5), int(image_y + _h + .5)
        buf_x0, img_x0 = (int(-img_x0 * _r + .5), 0) if img_x0 < 0 else (0, img_x0)
        buf_x1, img_x1 = (self.buf.shape[1] - int((img_x1 - src.shape[1]) * _r + .5), src.shape[1]) if img_x1 > src.shape[1] else (self.buf.shape[1], img_x1)
        buf_y0, img_y0 = (int(-img_y0 * _r + .5), 0) if img_y0 < 0 else (0, img_y0)
        buf_y1, img_y1 = (self.buf.shape[0] - int((img_y1 - src.shape[0]) * _r + .5), src.shape[0]) if img_y1 > src.shape[0] else (self.buf.shape[0], img_y1)
        self.buf[...] = 0
        _w2 = buf_x1 - buf_x0
        _h2 = buf_y1 - buf_y0
        self.buf[buf_y0:buf_y1, buf_x0:buf_x1, :] = cv2.resize(src[img_y0:img_y1, img_x0:img_x1, :], (_w2, _h2), interpolation=cv2.INTER_AREA)

    def __ensure_stop_saving(self):
        if self.saving:
            th = self.saving
            self.saving = None
            th.join()

    def __make_movie(self, output_path):
        self.saving = threading.Thread(
            target=self.__movie_save_worker, 
            args=(output_path, ), 
            daemon=True, 
        )
        self.saving.start()

    def __movie_save_worker(self, output_path):
        total = self.sequence.items[0].still_t * FPS
        total += sum([(item.trans_t + item.still_t) * FPS for item in self.sequence.items[1:]])
        with FrameWriter(str(output_path), size=MOVIE_SIZE, fps=FPS, qmax=16) as writer:
            try:
                counter = 1
                for seq0, seq1 in zip([None] + self.sequence.items[:-1], self.sequence.items):
                    wx.QueueEvent(self, MovieSavingEvent(counter, total))
                    for buf in self.__enum_render_frame(seq0, seq1):
                        if self.saving is None:
                            raise StopIteration
                        writer.write(self.buf)
                        counter += 1
                        wx.QueueEvent(self, MovieSavingEvent(counter, total))
            except StopIteration:
                pass
        wx.QueueEvent(self, MovieSavingEvent(0, 0))

    def __enum_render_frame(self, seq0, seq1):
        if seq0:
            count = int(seq1.trans_t * FPS + .5) + 1
            xs = sigmoid_space(seq0.x, seq1.x, count, seq1.init_v, seq1.final_v)
            ys = sigmoid_space(seq0.y, seq1.y, count, seq1.init_v, seq1.final_v)
            ws = sigmoid_space(seq0.w, seq1.w, count, seq1.init_v, seq1.final_v)
            for _x, _y, _w in zip(xs[:-1], ys[:-1], ws[:-1]):
                self.__render_buf(_x, _y, _w)
                yield self.buf

        self.__render_buf(seq1.x, seq1.y, seq1.w)
        for i in range(int(seq1.still_t * FPS + .5)):
            yield self.buf

    def __on_input_file_changed(self, event):
        path = get_path(self.input_file_picker.GetPath())
        if not path_exists(path):
            event.Skip()
            return
        self.__clear()
        self.raw_image = cv2.cvtColor(cv2.imread(str(path), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB)
        self.thumb_ratio = dpi_aware(self, THUMBNAIL_HEIGHT) / self.raw_image.shape[0]
        self.thumb_image = cv2.resize(self.raw_image, (int(self.raw_image.shape[1] * self.thumb_ratio), dpi_aware(self, THUMBNAIL_HEIGHT)), interpolation=cv2.INTER_AREA)
        self.input_image_thumbnail.set_image(self.thumb_image)
        self.input_image_thumbnail.set_image_zoom_position(0, dpi_aware(self, THUMBNAIL_HEIGHT)//2, 1.0)
        self.seq_x.SetMax(self.raw_image.shape[1])
        self.seq_y.SetMax(self.raw_image.shape[0])
        self.seq_w.SetMax(self.raw_image.shape[1])
        self.load_button.Enable()
        event.Skip()

    def __on_seq_list_item_selected(self, event):
        selected_index = self.sequence_list.GetFirstSelected()
        selected = selected_index > -1
        self.add_button.Enable(selected)
        self.change_button.Enable(selected)
        self.delete_button.Enable(selected)
        self.up_button.Enable(selected)
        self.down_button.Enable(selected)
        if selected:
            self.__set_form(self.sequence.items[selected_index])
        else:
            self.__clear_form()
        event.Skip()

    def __on_seq_list_begin_drag(self, event):
        data = wx.TextDataObject(str(event.GetIndex()))
        drop_source = wx.DropSource(self.sequence_list)
        drop_source.SetData(data)
        drop_source.DoDragDrop(flags=wx.Drag_DefaultMove)

    def __handle_drop(self, x, y, data):
        dragged_index = int(data)
        pos = wx.Point(x, y)
        index, _ = self.sequence_list.HitTest(pos)
        if index == wx.NOT_FOUND:
            index = len(self.sequence.items) - 1
        item = self.sequence.items.pop(dragged_index)
        self.sequence.items.insert(index, item)
        self.__clear_form()
        self.__update_sequence_list(index)
        return index

    def __update_setting(self):
        if self.raw_image is None:
            return
        x = get_spin_ctrl_value(self.seq_x)
        y = get_spin_ctrl_value(self.seq_y)
        w = get_spin_ctrl_value(self.seq_w)
        self.raw_image_x = x
        self.raw_image_y = y
        self.raw_image_w = w
        self.__render_buf(x, y, w)
        self.previewer.set_image(self.buf)

    def __save_sequence_list(self):
        if self.raw_image is None:
            wx.MessageBox('ステッチング画像が読み込まれていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            return
        if  len(self.sequence.items) < 1:
            wx.MessageBox('動画で表示したい場所のリストが空です。', 'エラー', wx.OK|wx.ICON_ERROR)
            return
        input_path = get_path(self.input_file_picker.GetPath())
        output_filename = input_path.stem + SEQUENCE_SUFFIX
        with wx.FileDialog(
            self, 
            '保存先ファイル名を入力してください。', 
            defaultDir=str(input_path.parent),
            defaultFile=output_filename,
            wildcard=SEQUENCE_FILE_WILDCARD,
            style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            output_path = get_path(fileDialog.GetPath())
            with open(output_path, 'w') as f:
                f.write(self.sequence.model_dump_json(indent=2))

    def __load_sequence_list(self):
        if self.raw_image is None:
            wx.MessageBox('ステッチング画像が読み込まれていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            return
        input_path = get_path(self.input_file_picker.GetPath()) 
        with wx.FileDialog(
            self, 
            '保存したファイル名を入力してください。', 
            defaultDir=str(input_path.parent),
            wildcard=SEQUENCE_FILE_WILDCARD,
            style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            self.__clear_form()
            with open(get_path(fileDialog.GetPath()), 'r') as f:
                self.sequence = SequenceModel.model_validate_json(f.read())
            self.__update_sequence_list()

    def __on_field_selected(self, event):
        x, y = event.field.get_center()
        w, h = event.field.get_size()
        x = int(x / self.thumb_ratio + .5)
        y = int(y / self.thumb_ratio + .5)
        w = int(w / self.thumb_ratio + .5)
        h = int(w * 9/16 + .5)  # w優先で16:9にする
        print(f'{w=} {h=} {self.raw_image.shape[0]=}')
        if h > self.raw_image.shape[0]:
            y = self.raw_image.shape[0] // 2
        else:
            y = min(max(h//2, y), self.raw_image.shape[0] - h//2)
        x = min(max(w//2, x), self.raw_image.shape[1] - w//2)
        self.raw_image_x = x
        self.raw_image_y = y
        self.raw_image_w = w
        self.seq_x.SetValue(x)
        self.seq_y.SetValue(y)
        self.seq_w.SetValue(w)
        self.add_button.Enable()
        self.__render_buf(x, y, w)
        self.previewer.set_image(self.buf)
        event.Skip()

    def __on_mouse_over_preview(self, event):
        x, y = event.image_x, event.image_y
        if x is None:
            if self.raw_image is None:
                self.info_x.SetLabel('')
                self.info_y.SetLabel('')
            else:
                self.info_x.SetLabel(f'---/{self.raw_image.shape[1]}')
                self.info_y.SetLabel(f'---/{self.raw_image.shape[0]}')
        else:
            r = self.raw_image_w / self.buf.shape[1]
            x = int((x - self.buf.shape[1] * .5) * r + self.raw_image_x + .5)
            y = int((y - self.buf.shape[0] * .5) * r + self.raw_image_y + .5)
            if 0 <= x < self.raw_image.shape[1] and 0 <= y < self.raw_image.shape[0]:
                self.info_x.SetLabel(f'{x}/{self.raw_image.shape[1]}')
                self.info_y.SetLabel(f'{y}/{self.raw_image.shape[0]}')
            else:
                self.info_x.SetLabel(f'---/{self.raw_image.shape[1]}')
                self.info_y.SetLabel(f'---/{self.raw_image.shape[0]}')
        event.Skip()

    def __on_input_value_changed(self, event):
        self.setting_changed_time = time.time()
        event.Skip()

    def __on_add_button_clicked(self, event):
        if self.previewer.get_image() is None:
            return
        item = SequenceItem(
            x=get_spin_ctrl_value(self.seq_x), 
            y=get_spin_ctrl_value(self.seq_y), 
            w=get_spin_ctrl_value(self.seq_w), 
            init_v=ACCELS[self.seq_init_v.GetSelection()].value, 
            final_v=DECELS[self.seq_final_v.GetSelection()].value, 
            trans_t=get_spin_ctrl_value(self.seq_trans_t), 
            still_t=get_spin_ctrl_value(self.seq_still_t), 
        )
        self.sequence.items.append(item)
        self.__clear_form()
        self.__update_sequence_list(len(self.sequence.items) - 1)
        event.Skip()

    def __on_change_button_clicked(self, event):
        if self.previewer.get_image() is None:
            return
        selected_index = self.sequence_list.GetFirstSelected()
        if selected_index > -1:
            item = self.sequence.items[selected_index]
            item.set_values(
                x=get_spin_ctrl_value(self.seq_x), 
                y=get_spin_ctrl_value(self.seq_y), 
                w=get_spin_ctrl_value(self.seq_w), 
                init_v=ACCELS[self.seq_init_v.GetSelection()].value, 
                final_v=DECELS[self.seq_final_v.GetSelection()].value, 
                trans_t=get_spin_ctrl_value(self.seq_trans_t), 
                still_t=get_spin_ctrl_value(self.seq_still_t), 
            )
            self.__clear_form()
            self.__update_sequence_list(selected_index)
        event.Skip()

    def __on_delete_button_clicked(self, event):
        if self.previewer.get_image() is None:
            return
        selected_index = self.sequence_list.GetFirstSelected()
        if selected_index > -1:
            self.sequence.items.pop(selected_index)
            if len(self.sequence.items) < 1:
                self.save_button.Enable(False)
            self.__clear_form()
            self.__update_sequence_list()
        event.Skip()

    def __on_up_button_clicked(self, event):
        if self.previewer.get_image() is None:
            return
        selected_index = self.sequence_list.GetFirstSelected()
        if selected_index > 0:
            item = self.sequence.items.pop(selected_index)
            index = selected_index - 1
            self.sequence.items.insert(index, item)
            self.__clear_form()
            self.__update_sequence_list(index)
        event.Skip()

    def __on_down_button_clicked(self, event):
        if self.previewer.get_image() is None:
            return
        selected_index = self.sequence_list.GetFirstSelected()
        if selected_index > -1 and selected_index < len(self.sequence.items) - 1:
            item = self.sequence.items.pop(selected_index)
            index = selected_index + 1
            self.sequence.items.insert(index, item)
            self.__clear_form()
            self.__update_sequence_list(index)
        event.Skip()

    def __on_save_button_clicked(self, event):
        self.__save_sequence_list()
        event.Skip()

    def __on_load_button_clicked(self, event):
        self.__load_sequence_list()
        event.Skip()

    def __on_start_button_clicked(self, event):
        if self.raw_image is None:
            wx.MessageBox('ステッチング画像が読み込まれていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return
        if  len(self.sequence.items) < 2:
            wx.MessageBox('動画で表示したい場所を2ヶ所以上追加してください。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return

        input_path = get_path(self.input_file_picker.GetPath())
        output_filename = input_path.with_suffix('.mp4')

        with wx.FileDialog(
            self, 
            '動画の保存先ファイル名を入力してください。', 
            defaultDir=str(input_path.parent),
            defaultFile=output_filename.name,
            wildcard=MOVIE_FILE_WILDCARD,
            style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            output_path = get_path(fileDialog.GetPath())
            self.output_filename_text.SetValue(str(output_path))
            try:
                self.__make_movie(output_path)
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

    def __on_setting_timer(self, event):
        if self.setting_changed_time is None:
            event.Skip()
            return
        if time.time() - self.setting_changed_time >= 1.0:
            self.setting_changed_time = None
            self.__update_setting()
        event.Skip()

    def __on_movie_saving(self, event):
        self.input_image_thumbnail.set_progress(event.total, event.current)

    def __on_close(self, event):
        self.setting_timer.Stop()
        self.__ensure_stop_saving()
        event.Skip()

    def on_save_menu(self, event):
        self.__save_sequence_list()
        event.Skip()

# MARK: drop target for listctrl
class ListDropTarget(wx.TextDropTarget):
    def __init__(self, on_drop_callback):
        super().__init__()
        self.on_drop_callback = on_drop_callback

    def OnDropText(self, x, y, data):
        index = self.on_drop_callback(x, y, data)
        return index is not None
