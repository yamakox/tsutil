import wx
import shutil
import matplotlib.pyplot as plt
from .common import APP_NAME
from .main_frame import MainFrame

plt.switch_backend('Agg')

# MARK: app instance

class MainApp(wx.App):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)

        # wxPythonのcontrolをシステム言語で表示できるようにする
        # NOTE: ただし、ファイル選択ダイアログは英語のまま
        lang_code = wx.Locale().GetSystemLanguage()
        locale = wx.Locale(lang_code)

    def OnInit(self):
        if not shutil.which('ffmpeg'):
            wx.MessageBox(
                "ffmpegが見つかりません。\nインストールしてください。",
                APP_NAME,
                wx.OK|wx.ICON_ERROR,
            )
        else:
            self.frame = MainFrame(None)
            self.frame.Show()
        return True

def main():
    app = MainApp()
    app.MainLoop()

if __name__ == "__main__":
    main()
