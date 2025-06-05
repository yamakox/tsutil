import wx
import sys

class ToolFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if sys.platform == 'darwin':
            menu_bar = wx.MenuBar()
            file_menu = wx.Menu()
            menu_close = file_menu.Append(wx.ID_CLOSE, 'Close Window\tCtrl+W')
            menu_bar.Append(file_menu, 'File')
            self.SetMenuBar(menu_bar)
            self.Bind(wx.EVT_MENU, self.__on_close, menu_close)

    def __on_close(self, event):
        self.Close()
