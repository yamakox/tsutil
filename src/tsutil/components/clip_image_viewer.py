import wx
from .base_image_viewer import *
from ..common import *

# MARK: constants

CORNER_SIZE = 16
PEN_WIDTH = 1
MIN_SIZE_RATIO = 0.2
DRAGGING_CORNER_LT = 301
DRAGGING_CORNER_RT = 302
DRAGGING_CORNER_RB = 303
DRAGGING_CORNER_LB = 304

# MARK: events

myEVT_CLIP_RECT_CHANGED = wx.NewEventType()
EVT_CLIP_RECT_CHANGED = wx.PyEventBinder(myEVT_CLIP_RECT_CHANGED)

class ClipRectChangedEvent(wx.ThreadEvent):
    def __init__(self, clip: Rect):
        super().__init__(myEVT_CLIP_RECT_CHANGED)
        self.clip = clip

# MARF: functions

def _even(x):
    return int(x + 1) & ~1

# MARK: main class

class ClipImageViewer(BaseImageViewer):
    def __init__(self, parent, clip: Rect, fields: list[Rect]=[], field_visible: bool=False, field_add_mode: bool=False, *args, **kwargs):
        super().__init__(parent, fields, field_visible, field_add_mode, *args, **kwargs)
        self.clip = clip
        self.CORNER_SIZE = dpi_aware(parent, CORNER_SIZE)
        self.PEN_WIDTH = dpi_aware(parent, PEN_WIDTH)

    def on_paint(self, event):
        super().on_paint(event)
        if self.image is None:
            return
        dc = wx.AutoBufferedPaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            gc.Clip(wx.Region(self.regions['preview']))
            if not self.clip.is_none():
                lt = self.get_view_position(self.clip.left, self.clip.top)
                rt = self.get_view_position(self.clip.right, self.clip.top)
                rb = self.get_view_position(self.clip.right, self.clip.bottom)
                lb = self.get_view_position(self.clip.left, self.clip.bottom)

                gc.SetPen(wx.Pen(wx.Colour(255, 128, 0, 192), width=self.PEN_WIDTH, style=wx.PENSTYLE_SOLID))
                gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 0)))
                path = gc.CreatePath()
                path.MoveToPoint(lt[0], lt[1])
                path.AddLineToPoint(rt[0] - self.PEN_WIDTH, rt[1])
                path.AddLineToPoint(rb[0] - self.PEN_WIDTH, rb[1] - self.PEN_WIDTH)
                path.AddLineToPoint(lb[0], lb[1] - self.PEN_WIDTH)
                path.CloseSubpath()
                gc.DrawPath(path)

                gc.SetPen(wx.NullPen)
                gc.SetBrush(wx.Brush(wx.Colour(255, 0, 0, 192)))
                gc.DrawRectangle(lt[0], lt[1], self.CORNER_SIZE, self.CORNER_SIZE)
                gc.DrawRectangle(rt[0] - self.CORNER_SIZE, rt[1], self.CORNER_SIZE, self.CORNER_SIZE)
                gc.DrawRectangle(rb[0] - self.CORNER_SIZE, rb[1] - self.CORNER_SIZE, self.CORNER_SIZE, self.CORNER_SIZE)
                gc.DrawRectangle(lb[0], lb[1] - self.CORNER_SIZE, self.CORNER_SIZE, self.CORNER_SIZE)
            gc.ResetClip()

    def on_mouse_down(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        cx, cy = self.get_view_position(self.clip.left, self.clip.top)
        if cx <= x < cx + self.CORNER_SIZE and cy <= y < cy  + self.CORNER_SIZE:
            self.CaptureMouse()
            self.dragging = DRAGGING_CORNER_LT
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        cx, cy = self.get_view_position(self.clip.right, self.clip.top)
        if cx - self.CORNER_SIZE <= x < cx and cy <= y < cy  + self.CORNER_SIZE:
            self.CaptureMouse()
            self.dragging = DRAGGING_CORNER_RT
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        cx, cy = self.get_view_position(self.clip.right, self.clip.bottom)
        if cx - self.CORNER_SIZE <= x < cx and cy - self.CORNER_SIZE <= y < cy:
            self.CaptureMouse()
            self.dragging = DRAGGING_CORNER_RB
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        cx, cy = self.get_view_position(self.clip.left, self.clip.bottom)
        if cx <= x < cx + self.CORNER_SIZE and cy - self.CORNER_SIZE <= y < cy:
            self.CaptureMouse()
            self.dragging = DRAGGING_CORNER_LB
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        super().on_mouse_down(event)

    def on_mouse_up(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        if self.dragging in [DRAGGING_CORNER_LT, DRAGGING_CORNER_RT, DRAGGING_CORNER_RB, DRAGGING_CORNER_LB]:
            wx.QueueEvent(self, ClipRectChangedEvent(self.clip))
            if self.HasCapture():
                self.ReleaseMouse()
            self.dragging = DRAGGING_NONE
            self.dragging_x, self.dragging_y = 0, 0
        else:
            super().on_mouse_up(event)

    def on_mouse_move(self, event):
        if self.image is None:
            return
        iw_min = int(self.image.shape[1] * MIN_SIZE_RATIO)
        ih_min = int(self.image.shape[0] * MIN_SIZE_RATIO)
        cx, cy = event.GetX() - self.dragging_x, event.GetY() - self.dragging_y
        cx = min(max(self.regions['preview'].GetLeft(), cx), self.regions['preview'].GetRight())
        cy = min(max(self.regions['preview'].GetTop(), cy), self.regions['preview'].GetBottom())
        if self.dragging == DRAGGING_CORNER_LT:
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(0, _even(ix)), self.clip.right - iw_min)
            iy = min(max(0, _even(iy)), self.clip.bottom - ih_min)
            self.clip.left = ix
            self.clip.top = iy
            self.Refresh()
        elif self.dragging == DRAGGING_CORNER_RT:
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(self.clip.left + iw_min, _even(ix)), self.image.shape[1])
            iy = min(max(0, _even(iy)), self.clip.bottom - ih_min)
            self.clip.right = ix
            self.clip.top = iy
            self.Refresh()
        elif self.dragging == DRAGGING_CORNER_RB:
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(self.clip.left + iw_min, _even(ix)), self.image.shape[1])
            iy = min(max(self.clip.top + ih_min, _even(iy)), self.image.shape[0])
            self.clip.right = ix
            self.clip.bottom = iy
            self.Refresh()
        elif self.dragging == DRAGGING_CORNER_LB:
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(0, _even(ix)), self.clip.right - iw_min)
            iy = min(max(self.clip.top + ih_min, _even(iy)), self.image.shape[0])
            self.clip.left = ix
            self.clip.bottom = iy
            self.Refresh()
        else:
            super().on_mouse_move(event)
