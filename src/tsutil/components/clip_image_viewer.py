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

    def on_paint(self, event):
        super().on_paint(event)
        if self.image is None:
            return
        dc = wx.PaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            gc.Clip(wx.Region(self.regions['preview']))
            if not self.clip.is_none():
                lt = self.get_view_position(self.clip.left, self.clip.top)
                rt = self.get_view_position(self.clip.right, self.clip.top)
                rb = self.get_view_position(self.clip.right, self.clip.bottom)
                lb = self.get_view_position(self.clip.left, self.clip.bottom)

                gc.SetPen(wx.Pen(wx.Colour(255, 128, 0, 192), width=PEN_WIDTH, style=wx.PENSTYLE_SOLID))
                gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 0)))
                path = gc.CreatePath()
                path.MoveToPoint(lt[0], lt[1])
                path.AddLineToPoint(rt[0] - PEN_WIDTH, rt[1])
                path.AddLineToPoint(rb[0] - PEN_WIDTH, rb[1] - PEN_WIDTH)
                path.AddLineToPoint(lb[0], lb[1] - PEN_WIDTH)
                path.CloseSubpath()
                gc.DrawPath(path)

                gc.SetPen(wx.NullPen)
                gc.SetBrush(wx.Brush(wx.Colour(255, 0, 0, 192)))
                gc.DrawRectangle(lt[0], lt[1], CORNER_SIZE, CORNER_SIZE)
                gc.DrawRectangle(rt[0] - CORNER_SIZE, rt[1], CORNER_SIZE, CORNER_SIZE)
                gc.DrawRectangle(rb[0] - CORNER_SIZE, rb[1] - CORNER_SIZE, CORNER_SIZE, CORNER_SIZE)
                gc.DrawRectangle(lb[0], lb[1] - CORNER_SIZE, CORNER_SIZE, CORNER_SIZE)
            gc.ResetClip()

    def on_mouse_down(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        cx, cy = self.get_view_position(self.clip.left, self.clip.top)
        if cx <= x < cx + CORNER_SIZE and cy <= y < cy  + CORNER_SIZE:
            self.dragging = DRAGGING_CORNER_LT
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        cx, cy = self.get_view_position(self.clip.right, self.clip.top)
        if cx - CORNER_SIZE <= x < cx and cy <= y < cy  + CORNER_SIZE:
            self.dragging = DRAGGING_CORNER_RT
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        cx, cy = self.get_view_position(self.clip.right, self.clip.bottom)
        if cx - CORNER_SIZE <= x < cx and cy - CORNER_SIZE <= y < cy:
            self.dragging = DRAGGING_CORNER_RB
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        cx, cy = self.get_view_position(self.clip.left, self.clip.bottom)
        if cx <= x < cx + CORNER_SIZE and cy - CORNER_SIZE <= y < cy:
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
            self.dragging = DRAGGING_NONE
            self.dragging_x, self.dragging_y = 0, 0
        else:
            super().on_mouse_up(event)

    def on_mouse_move(self, event):
        if self.image is None:
            return
        iw_min = int(self.image.shape[1] * MIN_SIZE_RATIO)
        ih_min = int(self.image.shape[0] * MIN_SIZE_RATIO)
        x = event.GetX()
        y = event.GetY()
        if self.dragging == DRAGGING_CORNER_LT:
            cx, cy = x - self.dragging_x, y - self.dragging_y
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(0, _even(ix)), self.clip.right - iw_min)
            iy = min(max(0, _even(iy)), self.clip.bottom - ih_min)
            self.clip.left = ix
            self.clip.top = iy
            self.Refresh()
        elif self.dragging == DRAGGING_CORNER_RT:
            cx, cy = x - self.dragging_x, y - self.dragging_y
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(self.clip.left + iw_min, _even(ix)), self.image.shape[1])
            iy = min(max(0, _even(iy)), self.clip.bottom - ih_min)
            self.clip.right = ix
            self.clip.top = iy
            self.Refresh()
        elif self.dragging == DRAGGING_CORNER_RB:
            cx, cy = x - self.dragging_x, y - self.dragging_y
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(self.clip.left + iw_min, _even(ix)), self.image.shape[1])
            iy = min(max(self.clip.top + ih_min, _even(iy)), self.image.shape[0])
            self.clip.right = ix
            self.clip.bottom = iy
            self.Refresh()
        elif self.dragging == DRAGGING_CORNER_LB:
            cx, cy = x - self.dragging_x, y - self.dragging_y
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(0, _even(ix)), self.clip.right - iw_min)
            iy = min(max(self.clip.top + ih_min, _even(iy)), self.image.shape[0])
            self.clip.left = ix
            self.clip.bottom = iy
            self.Refresh()
        else:
            super().on_mouse_move(event)
