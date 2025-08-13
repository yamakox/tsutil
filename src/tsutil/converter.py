import wx
import wx.adv
from pydantic import BaseModel
import cv2
from PIL import Image
import threading
from ffio import FrameWriter
from .common import *
from .tool_frame import ToolFrame
from .components.image_viewer import ImageViewer, SCROLL_BAR_SIZE
from .functions import sin_space

# MARK: constants

MARGIN = 16
THUMBNAIL_HEIGHT = 100
THUMBNAIL_SIZE = (1000, THUMBNAIL_HEIGHT + SCROLL_BAR_SIZE)
THUMBNAIL_HIGHLIGHT_COLOR = np.array((255, 255, 255), dtype=int)
TOOL_NAME = 'ステッチング画像から動画に変換'

class MovieSize(BaseModel):
    width: int = 1280
    height: int = 720
    description: str = 'HD'

class ThumbHeight(BaseModel):
    value: float = 1.0
    description: str = 'x 1.0'

class FrameRate(BaseModel):
    value: int = 60
    description: str = '60秒'
    gif: bool = False

MOVIE_SIZES = [
    MovieSize(width=1280, height=720, description='HD (1280x720)'),
    MovieSize(width=720, height=480, description='SD (720x480)'),
    MovieSize(width=1920, height=1080, description='フルHD (1920x1080)'),
    MovieSize(width=3840, height=2160, description='4K (3840x2160)'),
]

THUMB_HEIGHTS = [
    ThumbHeight(value=1.0, description='サムネイルあり'),
    ThumbHeight(value=0.0, description='サムネイルなし'),
    ThumbHeight(value=1.5, description='高さを1.5倍にする'),
    ThumbHeight(value=2.0, description='高さを2.0倍にする'),
]

FRAME_RATES = [
    FrameRate(value=60, description='60 fps'),
    FrameRate(value=30, description='30 fps'),
    FrameRate(value=15, description='15 fps'),
    FrameRate(value=5, description='5 fps (GIF)', gif=True),
    FrameRate(value=2, description='2 fps (GIF)', gif=True),
    FrameRate(value=1, description='1 fps (GIF)', gif=True),
]

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
        self.enable_save_menu(False)
        self.raw_image = None
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
        self.input_image_thumbnail = ImageViewer(panel, min_size=THUMBNAIL_SIZE, enable_zoom=False)
        sizer.Add(self.input_image_thumbnail, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # setting panel
        setting_panel = self.__make_setting_panel(panel)
        sizer.Add(setting_panel, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        sizer.AddGrowableRow(row)
        row += 1

        # save button
        save_button = wx.Button(panel, label='ステッチング画像から動画に変換する...')
        save_button.Bind(wx.EVT_BUTTON, self.__on_save_button_clicked)
        sizer.Add(save_button, flag=wx.ALIGN_CENTER)

        # output file panel
        output_file_panel = wx.Panel(panel)
        output_file_sizer = wx.FlexGridSizer(cols=3, gap=wx.Size(MARGIN, 0))
        output_file_sizer.AddGrowableCol(1)
        output_file_sizer.Add(wx.StaticText(output_file_panel, label='動画ファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.output_filename_text = wx.TextCtrl(output_file_panel, value='', style=wx.TE_READONLY)
        output_file_sizer.Add(self.output_filename_text, flag=wx.EXPAND)
        folder_button = wx.Button(output_file_panel, label='フォルダーを開く')
        folder_button.Bind(wx.EVT_BUTTON, self.__on_folder_button_clicked)
        output_file_sizer.Add(folder_button, flag=wx.ALIGN_CENTER_VERTICAL)
        output_file_panel.SetSizerAndFit(output_file_sizer)
        sizer.Add(output_file_panel, flag=wx.EXPAND|wx.TOP, border=MARGIN)
        row += 1

        panel.SetSizer(sizer)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=16)
        self.SetSizerAndFit(frame_sizer)

        self.Bind(EVT_MOVIE_SAVING, self.__on_movie_saving)
        self.Bind(wx.EVT_CLOSE, self.__on_close)

    def __make_setting_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(100, 0))
        sizer.AddGrowableRow(0)
        sizer.AddGrowableCol(0)

        left_panel = wx.Panel(panel)
        left_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(8, 8))
        left_sizer.AddGrowableCol(0)

        left_sizer.Add(wx.StaticText(left_panel, label='動画のサイズ:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.movie_size_selector = wx.Choice(left_panel)
        self.movie_size_selector.Append([i.description for i in MOVIE_SIZES])
        self.movie_size_selector.SetSelection(0)
        left_sizer.Add(self.movie_size_selector, flag=wx.EXPAND)

        left_sizer.Add(wx.StaticText(left_panel, label='サムネイル:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.thumb_height_selector = wx.Choice(left_panel)
        self.thumb_height_selector.Append([i.description for i in THUMB_HEIGHTS])
        self.thumb_height_selector.SetSelection(0)
        left_sizer.Add(self.thumb_height_selector, flag=wx.EXPAND)

        left_sizer.Add(wx.StaticText(left_panel, label='動画の秒数:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.second = wx.SpinCtrl(left_panel, value="60", min=1, max=180, style=wx.SP_ARROW_KEYS|wx.ALIGN_RIGHT)
        left_sizer.Add(self.second, flag=wx.EXPAND)

        left_sizer.Add(wx.StaticText(left_panel, label='フレームレート:', style=wx.ALIGN_RIGHT|wx.ST_NO_AUTORESIZE), flag=wx.EXPAND)
        self.frame_rate_selector = wx.Choice(left_panel)
        self.frame_rate_selector.Append([i.description for i in FRAME_RATES])
        self.frame_rate_selector.SetSelection(0)
        left_sizer.Add(self.frame_rate_selector, flag=wx.EXPAND)

        left_panel.SetSizerAndFit(left_sizer)
        sizer.Add(left_panel, flag=wx.ALIGN_LEFT)

        right_panel = wx.Panel(panel)
        right_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(8, 8))
        right_sizer.AddGrowableCol(0)

        self.ltr_button = wx.RadioButton(right_panel, label='左から右へスクロール', style=wx.RB_GROUP)
        self.ltr_button.SetValue(True)
        right_sizer.Add(self.ltr_button, flag=wx.ALIGN_LEFT)
        self.rtl_button = wx.RadioButton(right_panel, label='右から左へスクロール')
        right_sizer.Add(self.rtl_button, flag=wx.ALIGN_LEFT|wx.BOTTOM, border=MARGIN)

        self.loop_no_button = wx.RadioButton(right_panel, label='終端に達したら動画は終了する(ループしない)', style=wx.RB_GROUP)
        self.loop_no_button.SetValue(True)
        right_sizer.Add(self.loop_no_button, flag=wx.ALIGN_LEFT)
        self.loop_forward_button = wx.RadioButton(right_panel, label='終端に達したら先頭に戻る(等速でループする)')
        right_sizer.Add(self.loop_forward_button, flag=wx.ALIGN_LEFT)
        self.loop_forward2_button = wx.RadioButton(right_panel, label='終端に達したら先頭に戻る(加速→減速でループする)')
        right_sizer.Add(self.loop_forward2_button, flag=wx.ALIGN_LEFT)
        self.loop_reverse_button = wx.RadioButton(right_panel, label='終端に達したら反対方向に戻る(加速→減速でループする)')
        right_sizer.Add(self.loop_reverse_button, flag=wx.ALIGN_LEFT|wx.BOTTOM, border=MARGIN)

        right_panel.SetSizerAndFit(right_sizer)
        sizer.Add(right_panel, flag=wx.ALIGN_LEFT)

        panel.SetSizerAndFit(sizer)
        return panel

    def __clear(self):
        self.raw_image = None

    def __ensure_stop_saving(self):
        if self.saving:
            th = self.saving
            self.saving = None
            th.join()

    def __make_movie(self, output_path):
        try:
            self.__ensure_stop_saving()
            movie_size = MOVIE_SIZES[self.movie_size_selector.GetSelection()]
            thumb_height = THUMB_HEIGHTS[self.thumb_height_selector.GetSelection()]
            seconds = get_spin_ctrl_value(self.second)
            frame_rate = FRAME_RATES[self.frame_rate_selector.GetSelection()]
            direction = 1 if self.ltr_button.GetValue() else -1
            loop = None
            if self.loop_forward_button.GetValue():
                loop = 'fwd'
            elif self.loop_forward2_button.GetValue():
                loop = 'fwd2'
            elif self.loop_reverse_button.GetValue():
                loop = 'rev'
        except Exception as excep:
            wx.MessageBox('入力パラメータエラー: ' + str(excep), 'エラー', wx.OK|wx.ICON_ERROR)
        
        self.saving = threading.Thread(
            target=self.__movie_save_worker, 
            args=(output_path, movie_size, thumb_height, seconds, frame_rate, direction, loop), 
            daemon=True, 
        )
        self.saving.start()

    def __movie_save_worker(self, output_path, movie_size, thumb_height, seconds, frame_rate, direction, loop):
        thumb_img = None
        thumb_buf = None
        thumb_size = [0, 0]
        if thumb_height.value > 0:
            thumb_size = [movie_size.width, int(thumb_height.value * self.raw_image.shape[0] * movie_size.width / self.raw_image.shape[1] + .5)]
            thumb_img = cv2.resize(self.raw_image, thumb_size, interpolation=cv2.INTER_AREA)
        h = movie_size.height - thumb_size[1]
        w = int((self.raw_image.shape[1] * h) / self.raw_image.shape[0] + .5)
        if thumb_img is not None:
            thumb_w = int((movie_size.width * movie_size.width) / w + .5)
            thumb_ox = 0
        img = cv2.resize(self.raw_image, (w, h), interpolation=cv2.INTER_AREA)
        if loop in ('fwd', 'fwd2'):
            if direction > 0:
                img = np.hstack((img, img[:, :movie_size.width, :]))
                if thumb_img is not None:
                    thumb_img = np.hstack((thumb_img, thumb_img[:, :thumb_w, :]))
            else:
                img = np.hstack((img[:, -movie_size.width:, :], img))
                if thumb_img is not None:
                    thumb_img = np.hstack((thumb_img[:, -thumb_w:, :], thumb_img))
                    thumb_ox = thumb_w
        if thumb_img is not None:
            thumb_buf = np.array(thumb_img)
        frame_count = frame_rate.value * seconds
        x_max = img.shape[1] - movie_size.width
        if loop == 'rev':
            x_positions = np.hstack((
                sin_space(0, x_max, 1 + frame_count // 2).astype(int)[:-1],
                sin_space(x_max, 0, 1 + frame_count // 2).astype(int)[:-1],
            ))
        elif loop == 'fwd':
            x_positions = np.linspace(0, x_max, 1 + frame_count, dtype=int)[:-1]
        elif loop == 'fwd2':
            x_positions = sin_space(0, x_max, 1 + frame_count).astype(int)[:-1]
        else:
            x_positions = np.linspace(0, x_max, frame_count, dtype=int)
        if direction < 0:
            x_positions = x_max - x_positions
        if frame_rate.gif:
            images = []
            for buf in self.__enum_frames(movie_size, img, w, h, thumb_img, thumb_w, thumb_ox, thumb_size, thumb_buf, direction, x_positions):
                images.append(Image.fromarray(buf))
            images[0].save(str(output_path), save_all=True, append_images=images[1:], duration=1000 // frame_rate.value, loop=None if loop is None else 0)
        else:
            with FrameWriter(str(output_path), size=(movie_size.width, movie_size.height), fps=frame_rate.value, qmax=16) as writer:
                for buf in self.__enum_frames(movie_size, img, w, h, thumb_img, thumb_w, thumb_ox, thumb_size, thumb_buf, direction, x_positions, writer.frame):
                    writer.write(buf)
        wx.QueueEvent(self, MovieSavingEvent(0, 0))

    def __enum_frames(self, movie_size, img, w, h, thumb_img, thumb_w, thumb_ox, thumb_size, thumb_buf, direction, x_positions, frame_buf=None):
        for i, x in enumerate(x_positions):
            if self.saving is None:
                return
            wx.QueueEvent(self, MovieSavingEvent(i + 1, len(x_positions)))
            buf = frame_buf if frame_buf is not None else np.empty((movie_size.height, movie_size.width, 3), dtype=np.uint8)
            buf[(movie_size.height - h):, :, :] = img[:, x:(x + movie_size.width), :]
            if thumb_img is not None:
                _x = int(thumb_img.shape[1] * x / img.shape[1] + .5)
                thumb_buf[...] = thumb_img[...]
                thumb_buf[:, _x:_x+thumb_w, :] = ((thumb_buf[:, _x:_x+thumb_w, :] + THUMBNAIL_HIGHLIGHT_COLOR) // 2).astype(np.uint8)
                buf[:thumb_size[1], :, :] = thumb_buf[:, thumb_ox:thumb_ox+thumb_size[0], :]
                if direction > 0 and _x + thumb_w > thumb_size[0]:
                    buf[:thumb_size[1], :thumb_w, :] = thumb_buf[:, -thumb_w:, :]
                elif direction < 0 and _x < thumb_ox:
                    buf[:thumb_size[1], -thumb_w:, :] = thumb_buf[:, :thumb_w, :]
            yield buf

    def __on_movie_saving(self, event):
        self.input_image_thumbnail.set_progress(event.total, event.current)

    def __on_input_file_changed(self, event):
        path = get_path(self.input_file_picker.GetPath())
        if not path_exists(path):
            event.Skip()
            return
        self.__clear()
        #self.raw_image = cv2.cvtColor(cv2.imread(str(path), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB)
        self.raw_image = np.asarray(Image.open(path))
        self.thumb_ratio = dpi_aware(self, THUMBNAIL_HEIGHT) / self.raw_image.shape[0]
        self.input_image_thumbnail.set_image(cv2.resize(self.raw_image, (int(self.raw_image.shape[1] * self.thumb_ratio), dpi_aware(self, THUMBNAIL_HEIGHT)), interpolation=cv2.INTER_AREA))
        self.input_image_thumbnail.set_image_zoom_position(0, dpi_aware(self, THUMBNAIL_HEIGHT)//2, 1.0)
        event.Skip()

    def __on_save_button_clicked(self, event):
        if self.raw_image is None:
            wx.MessageBox('ステッチング画像が読み込まれていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return

        input_path = get_path(self.input_file_picker.GetPath())
        frame_rate = FRAME_RATES[self.frame_rate_selector.GetSelection()]
        if frame_rate.gif:
            output_filename = input_path.with_suffix('.gif')
        else:
            output_filename = input_path.with_suffix('.mp4')

        with wx.FileDialog(
            self, 
            '動画の保存先ファイル名を入力してください。', 
            defaultDir=str(input_path.parent),
            defaultFile=output_filename.name,
            wildcard=GIF_FILE_WILDCARD if frame_rate.gif else MOVIE_FILE_WILDCARD,
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

    def __on_close(self, event):
        self.__ensure_stop_saving()
        event.Skip()
