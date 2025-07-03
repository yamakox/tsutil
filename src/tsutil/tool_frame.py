import wx
import sys

class ToolFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if sys.platform == 'darwin':
            menu_bar = wx.MenuBar()
            file_menu = wx.Menu()
            self.file_menu_save = file_menu.Append(wx.ID_SAVE, 'Save Setting\tCtrl+S')
            file_menu.AppendSeparator()
            self.file_menu_close = file_menu.Append(wx.ID_CLOSE, 'Close Window\tCtrl+W')
            menu_bar.Append(file_menu, 'File')
            self.SetMenuBar(menu_bar)
            self.Bind(wx.EVT_MENU, self.on_close_menu, self.file_menu_close)
            self.Bind(wx.EVT_MENU, self.on_save_menu, self.file_menu_save)
        elif sys.platform == 'win32':
            self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_3DFACE))

    def on_close_menu(self, event):
        self.Close()
        event.Skip()

    def on_save_menu(self, event):
        event.Skip()

    def enable_save_menu(self, enable: bool):
        if sys.platform == 'darwin':
            self.file_menu_save.Enable(enable)
