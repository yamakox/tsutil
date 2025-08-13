import wx
import wx.adv
import cv2
from PIL import Image
from .common import *
from .tool_frame import ToolFrame
from .components.video_thumbnail import VideoThumbnail, EVT_VIDEO_LOADED, EVT_VIDEO_POSITION_CHANGED
from .components.image_viewer import ImageViewer
from .functions import get_common_prefix

# MARK: constants

MARGIN = 12
PREVIEW_SIZE = (300, 300)
POSITION_LIST_SIZE = (600, 250)
TOOL_NAME = '連続画像のカタログファイルの分割・結合'

# MARK: main window

class MainFrame(ToolFrame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=TOOL_NAME, *args, **kw)
        self.enable_save_menu(False)
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
        input_file_sizer.Add(wx.StaticText(input_file_panel, label='分割する連続画像のカタログファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.input_file_picker = wx.FilePickerCtrl(
            input_file_panel,
            message='分割する連続画像のカタログファイルを選択してください。',
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
        input_video_sizer.AddGrowableCol(0)
        input_video_sizer.Add(wx.StaticText(input_video_panel, label='赤い▲をドラッグして、分割場所のフレームを選択してください。'), flag=wx.ALIGN_CENTER)
        self.input_video_thumbnail = VideoThumbnail(input_video_panel, use_x_arrow=True)
        self.input_video_thumbnail.Bind(EVT_VIDEO_LOADED, self.__on_video_loaded)
        self.input_video_thumbnail.Bind(EVT_VIDEO_POSITION_CHANGED, self.__on_video_position_changed)
        input_video_sizer.Add(self.input_video_thumbnail, flag=wx.EXPAND)
        input_video_panel.SetSizerAndFit(input_video_sizer)
        sizer.Add(input_video_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # setting panel
        setting_panel = self.__make_setting_panel(panel)
        sizer.Add(setting_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        sizer.AddGrowableRow(row)
        row += 1

        # split button
        split_button = wx.Button(panel, label='分割した連続画像のカタログファイルを保存する')
        split_button.Bind(wx.EVT_BUTTON, self.__on_split_button_clicked)
        sizer.Add(split_button, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 1

        # hairline
        hr = wx.Panel(panel)
        hr.SetMaxSize(wx.Size(-1, 1))
        hr.SetBackgroundColour(wx.Colour(192, 192, 192, 255))
        sizer.Add(hr, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # merge button
        merge_button = wx.Button(panel, label='連続画像のカタログファイルを結合する...')
        merge_button.Bind(wx.EVT_BUTTON, self.__on_merge_button_clicked)
        sizer.Add(merge_button, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=MARGIN)
        row += 1

        # output video thumbnail 
        output_video_panel = wx.Panel(panel)
        output_video_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        output_video_sizer.AddGrowableCol(0)
        self.output_video_thumbnail = VideoThumbnail(output_video_panel)
        output_video_sizer.Add(self.output_video_thumbnail, flag=wx.EXPAND)
        output_video_panel.SetSizerAndFit(output_video_sizer)
        sizer.Add(output_video_panel, flag=wx.EXPAND|wx.BOTTOM, border=MARGIN)
        row += 1

        # output file panel
        output_file_panel = wx.Panel(panel)
        output_file_sizer = wx.FlexGridSizer(cols=3, gap=wx.Size(MARGIN, 0))
        output_file_sizer.AddGrowableCol(1)
        output_file_sizer.Add(wx.StaticText(output_file_panel, label='結合した連続画像のカタログファイル:'), flag=wx.ALIGN_CENTER_VERTICAL)
        self.output_filename_text = wx.TextCtrl(output_file_panel, value='', style=wx.TE_READONLY)
        output_file_sizer.Add(self.output_filename_text, flag=wx.EXPAND)
        folder_button = wx.Button(output_file_panel, label='フォルダーを開く')
        folder_button.Bind(wx.EVT_BUTTON, self.__on_folder_button_clicked)
        output_file_sizer.Add(folder_button, flag=wx.ALIGN_CENTER_VERTICAL)
        output_file_panel.SetSizerAndFit(output_file_sizer)
        sizer.Add(output_file_panel, flag=wx.EXPAND)
        row += 1

        panel.SetSizer(sizer)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=16)
        self.SetSizerAndFit(frame_sizer)

    def __make_setting_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(MARGIN, 0))
        sizer.AddGrowableRow(0)
        sizer.AddGrowableCol(1)

        setting_panel = wx.Panel(panel)
        setting_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 8))
        row = 0

        self.position_list = wx.ListCtrl(setting_panel, name='position_list', size=dpi_aware_size(parent, wx.Size(*POSITION_LIST_SIZE)), style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.position_list.InsertColumn(0, '分割ファイル名', wx.LIST_FORMAT_LEFT, width=350)
        self.position_list.InsertColumn(1, 'フレーム', wx.LIST_FORMAT_CENTER, width=230)
        self.position_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.__on_selection_changed)
        self.position_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.__on_selection_changed)
        setting_sizer.Add(self.position_list, flag=wx.EXPAND)
        setting_sizer.AddGrowableRow(row)
        row += 1

        option_panel = wx.Panel(setting_panel)
        option_sizer = wx.FlexGridSizer(cols=2, gap=wx.Size(6, 0))
        self.add_button = wx.Button(option_panel, label='分割場所の追加')
        self.add_button.Enable(False)
        self.add_button.Bind(wx.EVT_BUTTON, self.__on_add_button_clicked)
        option_sizer.Add(self.add_button, flag=wx.EXPAND)
        self.delete_button = wx.Button(option_panel, label='削除')
        self.delete_button.Enable(False)
        self.delete_button.Bind(wx.EVT_BUTTON, self.__on_delete_button_clicked)
        option_sizer.Add(self.delete_button, flag=wx.EXPAND)
        option_panel.SetSizerAndFit(option_sizer)
        setting_sizer.Add(option_panel, flag=wx.EXPAND)
        row += 1

        setting_panel.SetSizerAndFit(setting_sizer)
        sizer.Add(setting_panel, flag=wx.EXPAND)

        preview_panel = wx.Panel(panel)
        preview_sizer = wx.FlexGridSizer(cols=1, gap=wx.Size(0, 0))
        preview_sizer.AddGrowableRow(0)
        preview_sizer.AddGrowableCol(0)

        self.previewer = ImageViewer(preview_panel, min_size=PREVIEW_SIZE)
        self.previewer.set_grid(True, True)
        preview_sizer.Add(self.previewer, flag=wx.EXPAND)

        preview_panel.SetSizerAndFit(preview_sizer)
        sizer.Add(preview_panel, flag=wx.EXPAND)

        panel.SetSizerAndFit(sizer)
        return panel

    def __clear(self):
        self.positions.clear()
        self.input_video_thumbnail.clear()
        self.output_video_thumbnail.clear()
        self.output_filename_text.SetValue('')
        self.position_list.DeleteAllItems()
        self.previewer.clear()

    def __update_position_list(self):
        self.position_list.DeleteAllItems()
        self.delete_button.Enable(False)
        input_path = get_path(self.input_file_picker.GetPath())
        if not input_path:
            return
        fn, ext = input_path.stem, input_path.suffix
        count = self.input_video_thumbnail.get_frame_count()
        for i, (b, e) in enumerate(zip([0] + self.positions, self.positions + [count - 1])):
            self.position_list.Append([
                f'{fn}_{i + 1}{ext}', 
                f'{b + 1} 〜 {e + 1}', 
            ])

    def __show_preview(self, position):
        image_catalog = self.input_video_thumbnail.get_image_catalog()
        if image_catalog is None:
            self.previewer.clear()
            return
        frame = cv2.imread(str(image_catalog[position]), cv2.IMREAD_UNCHANGED)
        if frame is None:
            self.previewer.clear()
            return
        self.previewer.set_image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def __on_input_file_changed(self, event):
        path = get_path(self.input_file_picker.GetPath())
        if not path_exists(path):
            event.Skip()
            return
        self.__clear()
        self.input_video_thumbnail.load_image_catalog(path)
        event.Skip()

    def __on_video_loaded(self, event):
        self.add_button.Enable(True)
        position = self.input_video_thumbnail.get_frame_position()
        self.__show_preview(position)
        self.__update_position_list()
        self.Refresh()
        event.Skip()

    def __on_video_position_changed(self, event):
        index = self.position_list.GetFirstSelected()
        if index > -1:
            self.position_list.Select(index, 0)
        position = self.input_video_thumbnail.get_frame_position()
        self.__show_preview(position)
        event.Skip()

    def __on_selection_changed(self, event):
        index = self.position_list.GetFirstSelected()
        if index > 0:
            position = self.positions[index - 1]
            self.__show_preview(position)
            self.input_video_thumbnail.set_frame_position(position)
            self.delete_button.Enable(True)
        else:
            self.previewer.clear()
            self.delete_button.Enable(False)
        event.Skip()

    def __on_add_button_clicked(self, event):
        pos = self.input_video_thumbnail.get_frame_position()
        if pos is None or pos in self.positions:
            event.Skip()
            return
        if pos == 0 or pos == self.input_video_thumbnail.get_frame_count() - 1:
            wx.MessageBox('先頭フレームまたは最終フレームを分割場所に設定できません。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return
        self.positions.append(pos)
        self.positions.sort()
        self.__update_position_list()

    def __on_delete_button_clicked(self, event):
        index = self.position_list.GetFirstSelected()
        if index > 0:
            self.positions.pop(index - 1)
            self.__update_position_list()

    def __on_split_button_clicked(self, event):
        image_catalog = self.input_video_thumbnail.get_image_catalog()
        if image_catalog is None:
            wx.MessageBox('連続画像のカタログファイルが読み込まれていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return
        if  not self.positions:
            wx.MessageBox('分割場所が設定されていません。', 'エラー', wx.OK|wx.ICON_ERROR)
            event.Skip()
            return
        input_path = get_path(self.input_file_picker.GetPath())
        output_dir, fn, ext = input_path.parent, input_path.stem, input_path.suffix
        files = list(output_dir.glob(f'{fn}_*{ext}'))
        print(files)
        if files:
            answer = wx.MessageBox('既に分割ファイルが存在します。\n上書きしますか?', '確認', wx.OK|wx.CANCEL|wx.ICON_QUESTION)
            if answer != wx.OK:
                event.Skip()
                return
        try:
            with open(input_path, 'r') as f:
                lines = f.readlines()
            for i, (b, e) in enumerate(zip([0] + self.positions, self.positions + [len(lines)])):
                with open(output_dir / f'{fn}_{i + 1}{ext}', 'w') as f:
                    f.writelines(lines[b:e])
            answer = wx.MessageBox(f'分割ファイルの保存が完了しました。\nフォルダーを開きますか?', '処理完了', wx.OK|wx.CANCEL|wx.ICON_QUESTION)
            if answer == wx.OK:
                wx.LaunchDefaultApplication(str(output_dir))
        except Exception as excep:
            wx.MessageBox(f'エラーが発生しました: {excep}', 'エラー', wx.OK|wx.ICON_ERROR)
        event.Skip()

    def __on_merge_button_clicked(self, event):
        with wx.FileDialog(
            self,
            '結合するカタログファイルを複数選択してください。', 
            wildcard=IMAGE_CATALOG_FILE_WILDCARD, 
            style=wx.FD_OPEN|wx.FD_MULTIPLE|wx.FD_FILE_MUST_EXIST
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                event.Skip()
                return
            paths = [get_path(i) for i in fileDialog.GetPaths()]
            if len(paths) < 2:
                wx.MessageBox(f'結合するカタログファイルは2つ以上選択してください。', 'エラー', wx.OK|wx.ICON_ERROR)
                event.Skip()
                return
            paths.sort()
        filename = get_common_prefix([i.stem for i in paths]).rstrip('_')
        if filename:
            filename += '_merged'
        with wx.FileDialog(
            self, 
            '結合したカタログファイルの保存先ファイル名を入力してください。', 
            defaultDir=str(paths[0].parent), 
            defaultFile=filename, 
            wildcard=IMAGE_CATALOG_FILE_WILDCARD, 
            style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            output_path = get_path(fileDialog.GetPath())
            self.output_filename_text.SetValue(str(output_path))
        try:
            lines = []
            for i in paths:
                with open(i, 'r') as f:
                    lines.extend(f.readlines())
            with open(output_path, 'w') as f:
                f.writelines(lines)
            self.output_video_thumbnail.load_image_catalog(output_path)
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
