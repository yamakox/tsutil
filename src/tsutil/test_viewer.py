import wx
import wx.lib.scrolledpanel as scrolled
import os
import sys

class ImageViewer(scrolled.ScrolledPanel):
    def __init__(self, parent, image_path):
        super().__init__(parent)
        self.original_image = wx.Image(image_path, wx.BITMAP_TYPE_ANY)
        self.scale = 1.0
        self.fit_to_window = True  # 追加：ウィンドウに合わせるフラグ

        self.bitmap = wx.StaticBitmap(self, bitmap=wx.Bitmap(self.original_image))
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.bitmap, 0, wx.ALL, 5)
        self.SetSizer(self.sizer)

        self.SetScrollRate(10, 10)
        self.SetupScrolling()

        self.dragging = False
        self.last_mouse_pos = (0, 0)

        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mouse_wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_mouse_move)
        self.Bind(wx.EVT_SIZE, self.on_resize)  # 追加

    def set_scale(self, scale: float):
        self.scale = max(0.1, min(3.0, scale))
        self.fit_to_window = False  # 手動ズーム時はフラグ解除
        self.update_image()

    def update_image(self):
        if self.fit_to_window:
            client_size = self.GetSize()
            img_w, img_h = self.original_image.GetSize()
            scale_w = client_size.width / img_w
            scale_h = client_size.height / img_h
            self.scale = min(scale_w, scale_h, 3.0)
        new_w = max(1, int(self.original_image.GetWidth() * self.scale))
        new_h = max(1, int(self.original_image.GetHeight() * self.scale))

        scaled = self.original_image.Scale(new_w, new_h, wx.IMAGE_QUALITY_HIGH)
        self.bitmap.SetBitmap(wx.Bitmap(scaled))
        self.sizer.Layout()
        self.SetupScrolling(scrollToTop=False)

    def on_resize(self, event):
        if self.fit_to_window:
            self.update_image()
        event.Skip()

    def on_mouse_wheel(self, event):
        if event.GetWheelRotation() > 0:
            self.scale *= 1.1
        else:
            self.scale /= 1.1
        self.set_scale(self.scale)
        wx.PostEvent(self.GetParent(), ZoomChangedEvent(self.scale))

    def on_left_down(self, event):
        self.dragging = True
        self.last_mouse_pos = event.GetPosition()
        self.CaptureMouse()

    def on_left_up(self, event):
        if self.dragging:
            self.dragging = False
            self.ReleaseMouse()

    def on_mouse_move(self, event):
        if self.dragging and event.Dragging() and event.LeftIsDown():
            current_pos = event.GetPosition()
            dx = self.last_mouse_pos[0] - current_pos.x
            dy = self.last_mouse_pos[1] - current_pos.y
            self.Scroll(self.GetViewStart()[0] + dx // 10, self.GetViewStart()[1] + dy // 10)
            self.last_mouse_pos = current_pos


# カスタムイベント
myEVT_ZOOM_CHANGED = wx.NewEventType()
EVT_ZOOM_CHANGED = wx.PyEventBinder(myEVT_ZOOM_CHANGED, 1)

class ZoomChangedEvent(wx.PyCommandEvent):
    def __init__(self, zoom):
        super().__init__(myEVT_ZOOM_CHANGED)
        self.zoom = zoom


class MainFrame(wx.Frame):
    def __init__(self, parent, image_path):
        super().__init__(parent=parent, title="高解像度画像ビューア", size=(1024, 800))

        if sys.platform == 'darwin':
            menu_bar = wx.MenuBar()
            file_menu = wx.Menu()
            menu_close = file_menu.Append(wx.ID_CLOSE, 'Close Window\tCtrl+W')
            menu_bar.Append(file_menu, 'File')
            self.SetMenuBar(menu_bar)
            self.Bind(wx.EVT_MENU, self.OnClose, menu_close)

        panel = wx.Panel(self)
        sizer = wx.FlexGridSizer(2, 1, 0, 0)
        sizer.AddGrowableRow(1)
        sizer.AddGrowableCol(0)
        panel.SetSizer(sizer)

        # ツールバー
        toolbar_panel = wx.Panel(panel)
        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self.slider = wx.Slider(toolbar_panel, value=100, minValue=10, maxValue=300, style=wx.SL_HORIZONTAL)
        self.reset_button = wx.Button(toolbar_panel, label="リセット")
        self.zoom_label = wx.StaticText(toolbar_panel, label="100%")
        toolbar.Add(wx.StaticText(toolbar_panel, label="ズーム："), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        toolbar.Add(self.slider, 1, wx.EXPAND | wx.RIGHT, 5)
        toolbar.Add(self.zoom_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        toolbar.Add(self.reset_button, 0)
        toolbar_panel.SetSizer(toolbar)

        # 画像ビューア
        self.viewer = ImageViewer(panel, image_path)

        sizer.Add(toolbar_panel, 0, wx.EXPAND | wx.ALL, 10)
        sizer.Add(self.viewer, 1, wx.EXPAND)

        # イベント
        self.slider.Bind(wx.EVT_SLIDER, self.on_slider)
        self.reset_button.Bind(wx.EVT_BUTTON, self.on_reset)
        self.Bind(EVT_ZOOM_CHANGED, self.on_zoom_changed)

        self.Show()

    def on_slider(self, event):
        value = self.slider.GetValue()
        scale = value / 100.0
        self.viewer.set_scale(scale)
        self.zoom_label.SetLabel(f"{int(scale * 100)}%")

    def on_reset(self, event):
        self.slider.SetValue(100)
        self.viewer.fit_to_window = True
        self.viewer.update_image()
        self.zoom_label.SetLabel("100%")

    def on_zoom_changed(self, event):
        scale_percent = int(event.zoom * 100)
        self.slider.SetValue(scale_percent)
        self.zoom_label.SetLabel(f"{scale_percent}%")

    def OnClose(self, event):
        self.Close()
