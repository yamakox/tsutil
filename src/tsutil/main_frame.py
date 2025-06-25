import wx
import wx.adv
import sys
from .common import *
from . import trimmer, extractor, corrector, adjuster
from typing import Callable
from importlib.metadata import version, metadata

# MARK: constants

PACKAGE_NAME = metadata(__package__).get('Name')
WINDOW_SIZE = (600, 400)
MARGIN = 16

# MARK: main window

class MainFrame(wx.Frame):
    def __init__(self, parent: wx.Window|None = None, *args, **kw):
        super().__init__(parent, title=f'{APP_NAME} v{version(PACKAGE_NAME)}', *args, **kw)

        self.SetSize(self.FromDIP(wx.Size(*WINDOW_SIZE)))
        if sys.platform == 'darwin':
            # Applicationメニューを表示してQuit(Cmd+Q)できるようにする
            menu_bar = wx.MenuBar()
            self.SetMenuBar(menu_bar)

        frame_sizer = wx.GridSizer(rows=1, cols=1, gap=wx.Size(0, 0))
        panel = wx.Panel(self)

        sizer = wx.GridSizer(cols=1, gap=wx.Size(0, MARGIN))

        buttons = [
            ('【 動画のトリミング 】', 'カメラで撮影した動画の不要な前後部分を無劣化で削除します。', self.__launch_trimmer),
            ('【 動画から連続画像の展開 】', 'カメラで撮影した動画の各フレームを連続した画像ファイルに展開します。\n展開時に輝度や色の調整を行うことができます。', self.__launch_extractor),
            ('【 画像のブレ・傾き・歪みの補正 】', '手持ち撮影した動画から展開した画像ファイルの\nブレ、水平出し、台形補正を行います。', self.__launch_corrector),
            ('【 ステッチング画像の縦横比の調整 】', 'ステッチング後の画像ファイルに対して\n一両ずつ長さと高さを調整します。', self.__launch_adjuster),
        ]
        for i, (mainLabel, note, callback) in enumerate(buttons):
            btn = self.__make_button(panel, mainLabel, note, callback)
            btn.DisableFocusFromKeyboard()
            if i == 0:
                sizer.Add(btn, flag=wx.EXPAND)
            else:
                sizer.Add(btn, flag=wx.EXPAND)

        panel.SetSizer(sizer)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=MARGIN)
        self.SetSizer(frame_sizer)

        self.Bind(wx.EVT_CLOSE, self.__on_close)

    def __make_button(self, panel: wx.Panel, mainLabel: str, note: str, callback: Callable[[wx.CommandEvent], None]) -> wx.adv.CommandLinkButton:
        btn = wx.adv.CommandLinkButton(panel, mainLabel=mainLabel, note=note)
        btn.Bind(wx.EVT_BUTTON, callback)
        return btn

    def __launch_trimmer(self, event):
        frame = trimmer.MainFrame(self)
        frame.Show()

    def __launch_extractor(self, event):
        frame = extractor.MainFrame(self)
        frame.Show()

    def __launch_corrector(self, event):
        frame = corrector.MainFrame(self)
        frame.Show()

    def __launch_adjuster(self, event):
        frame = adjuster.MainFrame(self)
        frame.Show()

    def __on_close(self, event):
        event.Skip()
