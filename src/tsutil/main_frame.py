import wx
import wx.adv
import sys
from typing import Callable
from importlib.metadata import version, metadata
import shutil
import subprocess
from .common import *
from . import trimmer, extractor, corrector, adjuster, converter, converter2, splitter

# MARK: constants

PACKAGE_NAME = metadata(__package__).get('Name')
WINDOW_SIZE = (800, 400)
MARGIN1 = 16
MARGIN2 = 8

# MARK: main window

class MainFrame(wx.Frame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=f'{APP_NAME} v{version(PACKAGE_NAME)}', *args, **kw)
        if sys.platform == 'win32':
            self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_3DFACE))

        self.SetSize(dpi_aware_size(self, wx.Size(*WINDOW_SIZE)))
        if sys.platform == 'darwin':
            # Applicationメニューを表示してQuit(Cmd+Q)できるようにする
            menu_bar = wx.MenuBar()
            self.SetMenuBar(menu_bar)

        frame_sizer = wx.GridSizer(rows=1, cols=1, gap=wx.Size(0, 0))
        panel = wx.Panel(self)


        buttons_group = [
            [
                (True, '【 動画のトリミング 】', 'カメラで撮影した動画の不要な前後部分を\n無劣化で削除します。', self.__launch_trimmer),
                (True, '【 動画から連続画像の展開 】', '動画の各フレームを連続した画像ファイルに展開します。\n展開時に輝度や色の調整を行うことができます。', self.__launch_extractor),
                (True, '【 連続画像のブレ・傾き・歪みの補正 】', '連続した画像ファイルの\nブレ、水平出し、台形補正を行います。', self.__launch_corrector),
                (True, '【 連続画像のカタログファイルの分割・結合 】', '連続画像を分けて画像補正処理する必要がある場合\n連続した画像のカタログファイルを分割・結合します。', self.__launch_splitter),
            ], 
            [
                (shutil.which('trainscanner') is not None, '【 TrainScanner 】', 'TrainScannerを起動します。\n', self.__launch_trainscanner), 
                (True, '【 ステッチング画像の縦横比の調整 】', 'ステッチング後の画像ファイルに対して\n一両ずつ長さと高さを調整します。', self.__launch_adjuster),
                (True, '【 ステッチング画像から動画に変換 】', 'ステッチング後の画像ファイルから\nSNSに投稿できる動画に変換します。', self.__launch_converter),
                (True, '【 ステッチング画像から動画に変換2 】', '拡大・縮小しながら表示位置が\n変わっていく複雑な動画を作成します。', self.__launch_converter2),
            ], 
        ]

        sizer = wx.GridSizer(cols=len(buttons_group), gap=wx.Size(MARGIN1, 0))

        for buttons in buttons_group:
            col_panel = wx.Panel(panel)
            col_sizer = wx.GridSizer(cols=1, gap=wx.Size(0, MARGIN2))
            for i, (flag, mainLabel, note, callback) in enumerate(buttons):
                if not flag:
                    continue
                btn = self.__make_button(col_panel, mainLabel, note, callback)
                col_sizer.Add(btn, flag=wx.EXPAND)
            col_panel.SetSizerAndFit(col_sizer)
            sizer.Add(col_panel, flag=wx.EXPAND)

        panel.SetSizer(sizer)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=MARGIN1)
        self.SetSizer(frame_sizer)

        self.Bind(wx.EVT_CLOSE, self.__on_close)

    def __make_button(self, panel: wx.Panel, mainLabel: str, note: str, callback: Callable[[wx.CommandEvent], None]) -> wx.adv.CommandLinkButton:
        btn = wx.adv.CommandLinkButton(panel, mainLabel=mainLabel, note=note)
        btn.DisableFocusFromKeyboard()
        btn.Bind(wx.EVT_BUTTON, callback)
        return btn

    def __launch_trimmer(self, event):
        frame = trimmer.MainFrame(self)
        frame.Show()

    def __launch_extractor(self, event):
        frame = extractor.MainFrame(self)
        frame.Show()

    def __launch_splitter(self, event):
        frame = splitter.MainFrame(self)
        frame.Show()

    def __launch_corrector(self, event):
        frame = corrector.MainFrame(self)
        frame.Show()

    def __launch_adjuster(self, event):
        frame = adjuster.MainFrame(self)
        frame.Show()

    def __launch_converter(self, event):
        frame = converter.MainFrame(self)
        frame.Show()

    def __launch_converter2(self, event):
        frame = converter2.MainFrame(self)
        frame.Show()

    def __launch_trainscanner(self, event):
        subprocess.Popen(['trainscanner'])

    def __on_close(self, event):
        event.Skip()
