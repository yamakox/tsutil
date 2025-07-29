import wx
from .image_viewer import *
from ..common import *

# MARK: constants

DRAGGING_RECT = 101

# MARK: events

myEVT_FIELD_SELECTED = wx.NewEventType()
EVT_FIELD_SELECTED = wx.PyEventBinder(myEVT_FIELD_SELECTED)

class FieldSelectedEvent(wx.ThreadEvent):
    def __init__(self, field: Rect):
        super().__init__(myEVT_FIELD_SELECTED)
        self.field = field

# MARK: main class

class RangeImageViewer(ImageViewer):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.dragging_rect = None
        self.dragging_x = None
        self.dragging_y = None

    def on_paint(self, event):
        super().on_paint(event)
        if self.image is None:
            return
        dc = wx.AutoBufferedPaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            gc.Clip(wx.Region(self.regions['preview']))
            if self.dragging_rect is not None:
                gc.SetPen(wx.Pen(wx.Colour(255, 0, 0, 255)))
                gc.SetBrush(wx.Brush(wx.Colour(255, 0, 0, 64)))
                self.__paint_rect(gc, self.dragging_rect)
            gc.ResetClip()

    def __paint_rect(self, gc, rect: Rect):
        x0, y0, x1, y1 = self.get_view_rect(*rect.to_tuple())
        # Penの太さの分だけ幅・高さが増加する
        gc.DrawRectangle(x0, y0, x1 - x0 - 1, y1 - y0 - 1)

    def on_mouse_down(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        ix, iy = self.get_image_position(mouse_pos=(x, y))
        if self.regions['preview'].Contains(x, y) and ix is not None:
            self.CaptureMouse()
            self.dragging = DRAGGING_RECT
            self.dragging_rect = Rect(left=ix, top=iy, right=ix, bottom=iy)
            self.dragging_x = ix
            self.dragging_y = iy
        else:
            super().on_mouse_down(event)

    def on_mouse_up(self, event):
        if self.image is None:
            return
        if self.dragging == DRAGGING_RECT:
            sz = self.dragging_rect.get_size()
            if sz[0] * sz[1]:
                if self.dragging_rect.right < self.dragging_rect.left:
                    self.dragging_rect.left, self.dragging_rect.right = self.dragging_rect.right, self.dragging_rect.left
                if self.dragging_rect.bottom < self.dragging_rect.top:
                    self.dragging_rect.top, self.dragging_rect.bottom = self.dragging_rect.bottom, self.dragging_rect.top
                wx.QueueEvent(self, FieldSelectedEvent(self.dragging_rect))
            if self.HasCapture():
                self.ReleaseMouse()
            self.dragging = DRAGGING_NONE
            self.dragging_rect = None
            self.dragging_x = None
            self.dragging_y = None
            self.Refresh()
        else:
            super().on_mouse_up(event)

    def on_mouse_move(self, event):
        if self.image is None:
            return
        if self.dragging == DRAGGING_RECT:
            x = min(max(self.regions['preview'].GetLeft(), event.GetX()), self.regions['preview'].GetRight())
            y = min(max(self.regions['preview'].GetTop(), event.GetY()), self.regions['preview'].GetBottom())
            ix, iy = self.get_image_position(mouse_pos=(x, y), range_limit=True)
            if ix is not None:
                if event.ShiftDown():
                    dx, dy = ix - self.dragging_x, iy - self.dragging_y
                    if abs(dx) > 16/9 * abs(dy):
                        dx = int(16/9 * dy + .5)
                    else:
                        dy = int(9/16 * dx + .5)
                    self.dragging_rect.left = self.dragging_x - dx
                    self.dragging_rect.right = self.dragging_x + dx
                    self.dragging_rect.top = self.dragging_y - dy
                    self.dragging_rect.bottom = self.dragging_y + dy
                else:
                    self.dragging_rect.left = self.dragging_x
                    self.dragging_rect.right = ix
                    self.dragging_rect.top = self.dragging_y
                    self.dragging_rect.bottom = iy
                self.Refresh()
        else:
            super().on_mouse_move(event)
