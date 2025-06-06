import wx
import wx.adv
import sys
from .common import *
from . import trimmer, extractor
from typing import Callable
from importlib.metadata import version, metadata

# MARK: constants

PACKAGE_NAME = metadata(__package__).get('Name')
WINDOW_SIZE = (600, 400)

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

        sizer = wx.GridSizer(rows=3, cols=1, gap=wx.Size(0, MARGIN))

        buttons = [
            ('【 動画のトリミング 】', 'カメラで撮影した動画の不要な前後部分を無劣化で削除します。', self.__launch_trimmer),
            ('【 動画から画像の展開 】', 'カメラで撮影した動画の各フレームを画像ファイルに展開します。\n展開時に輝度や色の調整を行うことができます。', self.__launch_extractor),
            ('【 画像のブレ・傾き・歪みの補正 】', '手持ち撮影した動画から展開した画像ファイルの\nブレ、水平出し、台形補正を行います。', self.__launch_corrector),
        ]
        for i, (mainLabel, note, callback) in enumerate(buttons):
            btn = self.__make_button(panel, mainLabel, note, callback)
            if i == 0:
                sizer.Add(btn, flag=wx.EXPAND)
            else:
                sizer.Add(btn, flag=wx.EXPAND)

        panel.SetSizer(sizer)

        frame_sizer.Add(panel, flag=wx.EXPAND|wx.ALL, border=MARGIN)
        self.SetSizer(frame_sizer)

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
        wx.MessageBox(
            "画像のブレ・傾き・歪みの補正",
            "画像のブレ・傾き・歪みの補正",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )
