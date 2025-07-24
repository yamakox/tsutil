import wx
import os
from pathlib import Path
from typing import Optional, List


class FileDropTarget(wx.FileDropTarget):
    """ファイルドロップターゲットクラス"""

    def __init__(self, window, valid_extensions: List[str], callback):
        super().__init__()
        self.window = window
        self.valid_extensions = [ext.lower() for ext in valid_extensions]
        self.callback = callback

    def OnDropFiles(self, x, y, filenames):
        """ファイルがドロップされた時の処理"""
        if not filenames:
            return False

        file_path = filenames[0]  # 最初のファイルのみを使用

        # ファイルの拡張子をチェック
        if self.valid_extensions:
            file_ext = Path(file_path).suffix.lower()
            if file_ext not in self.valid_extensions:
                wx.MessageBox(
                    f"サポートされていないファイル形式です。\n"
                    f'対応形式: {", ".join(self.valid_extensions)}',
                    "エラー",
                    wx.OK | wx.ICON_ERROR,
                )
                return False

        # ファイルが存在するかチェック
        if not os.path.exists(file_path):
            wx.MessageBox("ファイルが見つかりません。", "エラー", wx.OK | wx.ICON_ERROR)
            return False

        # コールバック関数を呼び出し
        self.callback(file_path)
        return True


class DragDropFilePickerCtrl(wx.Panel):
    """Drag&Drop機能付きFilePickerCtrl"""

    def __init__(self, parent, message="", wildcard="", style=0, **kwargs):
        super().__init__(parent, **kwargs)

        # wildcard から拡張子を抽出
        self.valid_extensions = self._extract_extensions_from_wildcard(wildcard)

        # イベントハンドラーを保存するためのリスト
        self._event_handlers = []

        # レイアウト作成
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        # FilePickerCtrl
        self.file_picker = wx.FilePickerCtrl(
            self, message=message, wildcard=wildcard, style=style
        )
        sizer.Add(self.file_picker, 1, wx.EXPAND)

        # Drag&Drop説明ラベル
        drop_label = wx.StaticText(self, label="またはここにファイルをドロップ")
        drop_label.SetForegroundColour(wx.Colour(128, 128, 128))
        sizer.Add(drop_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)

        self.SetSizer(sizer)

        # Drag&Drop設定
        drop_target = FileDropTarget(self, self.valid_extensions, self._on_file_dropped)
        self.SetDropTarget(drop_target)
        self.file_picker.SetDropTarget(
            FileDropTarget(
                self.file_picker, self.valid_extensions, self._on_file_dropped
            )
        )

    def _extract_extensions_from_wildcard(self, wildcard: str) -> List[str]:
        """wildcardから拡張子リストを抽出"""
        extensions = []
        if not wildcard:
            return extensions

        # wildcard例: 'Movie files (*.mp4;*.mov;*.m4v)|*.mp4;*.mov;*.m4v'
        parts = wildcard.split("|")
        if len(parts) >= 2:
            ext_part = parts[1]
            # *.mp4;*.mov;*.m4v から拡張子を抽出
            for ext in ext_part.split(";"):
                ext = ext.strip()
                if ext.startswith("*."):
                    extensions.append(ext[1:])  # .mp4, .mov, .m4v

        return extensions

    def _on_file_dropped(self, file_path: str):
        """ファイルがドロップされた時の処理"""
        self.file_picker.SetPath(file_path)

        # 保存されたイベントハンドラーを直接呼び出し
        for handler in self._event_handlers:
            # 簡易的なイベントオブジェクトを作成
            class FilePickerEvent:
                def __init__(self, path):
                    self.path = path

                def GetPath(self):
                    return self.path

                def Skip(self):
                    pass

            # ハンドラーを呼び出し
            try:
                handler(FilePickerEvent(file_path))
            except Exception as e:
                print(f"Error calling event handler: {e}")

    def GetPath(self) -> str:
        """選択されたファイルパスを取得"""
        return self.file_picker.GetPath()

    def SetPath(self, path: str):
        """ファイルパスを設定"""
        self.file_picker.SetPath(path)

    def Bind(self, event_type, handler):
        """イベントバインド"""
        if event_type == wx.EVT_FILEPICKER_CHANGED:
            # EVT_FILEPICKER_CHANGEDハンドラーを内部で保存
            self._event_handlers.append(handler)
        self.file_picker.Bind(event_type, handler)
