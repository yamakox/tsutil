import wx
from .base_image_viewer import *
from ..common import *

# MARK: constants

CORNER_SIZE = 16
PEN_WIDTH = 1
MIN_SIZE_RATIO = 0.2
DRAGGING_CORNER_LT = 201
DRAGGING_CORNER_RT = 202
DRAGGING_CORNER_RB = 203
DRAGGING_CORNER_LB = 204

# MARK: events

myEVT_PERSPECTIVE_POINTS_CHANGED = wx.NewEventType()
EVT_PERSPECTIVE_POINTS_CHANGED = wx.PyEventBinder(myEVT_PERSPECTIVE_POINTS_CHANGED)

class PerspectivePointsChangedEvent(wx.ThreadEvent):
    def __init__(self, perspective_points: PerspectivePoints):
        super().__init__(myEVT_PERSPECTIVE_POINTS_CHANGED)
        self.perspective_points = perspective_points

# MARK: main class

class DeshakingImageViewer(BaseImageViewer):
    def __init__(self, parent, perspective_points: PerspectivePoints, fields: list[Rect]=[], field_visible: bool=False, field_add_mode: bool=False, *args, **kwargs):
        super().__init__(parent, fields, field_visible, field_add_mode, *args, **kwargs)
        self.perspective_points = perspective_points
        self.CORNER_SIZE = dpi_aware(parent, CORNER_SIZE)
        self.PEN_WIDTH = dpi_aware(parent, PEN_WIDTH)

    def on_paint(self, event):
        super().on_paint(event)
        if self.image is None:
            return
        dc = wx.BufferedPaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            gc.Clip(wx.Region(self.regions['preview']))
            if not self.perspective_points.is_none():
                p = self.perspective_points
                lt = self.get_view_position(*p.left_top.to_tuple())
                rt = self.get_view_position(*p.right_top.to_tuple())
                rb = self.get_view_position(*p.right_bottom.to_tuple())
                lb = self.get_view_position(*p.left_bottom.to_tuple())

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
        p = self.perspective_points
        cx, cy = self.get_view_position(*p.left_top.to_tuple())
        if cx <= x < cx + self.CORNER_SIZE and cy <= y < cy  + self.CORNER_SIZE:
            self.CaptureMouse()
            self.dragging = DRAGGING_CORNER_LT
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        cx, cy = self.get_view_position(*p.right_top.to_tuple())
        if cx - self.CORNER_SIZE <= x < cx and cy <= y < cy  + self.CORNER_SIZE:
            self.CaptureMouse()
            self.dragging = DRAGGING_CORNER_RT
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        cx, cy = self.get_view_position(*p.right_bottom.to_tuple())
        if cx - self.CORNER_SIZE <= x < cx and cy - self.CORNER_SIZE <= y < cy:
            self.CaptureMouse()
            self.dragging = DRAGGING_CORNER_RB
            self.dragging_x, self.dragging_y = x - cx, y - cy
            return
        cx, cy = self.get_view_position(*p.left_bottom.to_tuple())
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
            wx.QueueEvent(self, PerspectivePointsChangedEvent(self.perspective_points))
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
            ix = min(max(0, int(ix + .5)), self.perspective_points.right_limit() - iw_min)
            iy = min(max(0, int(iy + .5)), self.perspective_points.bottom_limit() - ih_min)
            self.perspective_points.left_top.x = ix
            self.perspective_points.left_top.y = iy
            self.Refresh()
        elif self.dragging == DRAGGING_CORNER_RT:
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(self.perspective_points.left_limit() + iw_min, int(ix + .5)), self.image.shape[1])
            iy = min(max(0, int(iy + .5)), self.perspective_points.bottom_limit() - ih_min)
            self.perspective_points.right_top.x = ix
            self.perspective_points.right_top.y = iy
            self.Refresh()
        elif self.dragging == DRAGGING_CORNER_RB:
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(self.perspective_points.left_limit() + iw_min, int(ix + .5)), self.image.shape[1])
            iy = min(max(self.perspective_points.top_limit() + ih_min, int(iy + .5)), self.image.shape[0])
            self.perspective_points.right_bottom.x = ix
            self.perspective_points.right_bottom.y = iy
            self.Refresh()
        elif self.dragging == DRAGGING_CORNER_LB:
            ix, iy = self.get_image_precise_position(mouse_pos=(cx, cy))
            ix = min(max(0, int(ix + .5)), self.perspective_points.right_limit() - iw_min)
            iy = min(max(self.perspective_points.top_limit() + ih_min, int(iy + .5)), self.image.shape[0])
            self.perspective_points.left_bottom.x = ix
            self.perspective_points.left_bottom.y = iy
            self.Refresh()
        else:
            super().on_mouse_move(event)
