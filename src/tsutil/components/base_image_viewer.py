import wx
from .image_viewer import *
from ..common import *

# MARK: constants

DRAGGING_RECT = 101

# MARK: events

myEVT_FIELD_ADDED = wx.NewEventType()
EVT_FIELD_ADDED = wx.PyEventBinder(myEVT_FIELD_ADDED)

class FieldAddedEvent(wx.ThreadEvent):
    def __init__(self, field: Rect):
        super().__init__(myEVT_FIELD_ADDED)
        self.field = field

myEVT_FIELD_DELETED = wx.NewEventType()
EVT_FIELD_DELETED = wx.PyEventBinder(myEVT_FIELD_DELETED)

class FieldDeletedEvent(wx.ThreadEvent):
    def __init__(self, field: Rect):
        super().__init__(myEVT_FIELD_DELETED)
        self.field = field

# MARK: main class

class BaseImageViewer(ImageViewer):
    def __init__(self, parent, fields: list[Rect], field_visible: bool=True, field_add_mode: bool=False, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.fields = fields
        self.field_visible = field_visible
        self.field_add_mode = field_add_mode
        self.dragging_rect = None

    def set_field_add_mode(self, mode):
        self.field_add_mode = mode

    def set_field_visible(self, field_visible: bool=True):
        self.field_visible = field_visible
        self.Refresh()

    def move_view_to_field(self, field: Rect):
        x, y = field.get_center()
        w, h = field.get_size()
        if w is None:
            return
        ratio_w = self.regions['preview'].GetWidth() / (w * 5)
        ratio_h = self.regions['preview'].GetHeight() / (h * 5)
        zoom = min(ratio_w, ratio_h)
        self.set_image_zoom_position(x, y, zoom)

    def on_paint(self, event, gc: wx.GraphicsContext):
        super().on_paint(event, gc)
        if self.image is None:
            return
        gc.Clip(wx.Region(self.regions['preview']))
        if self.field_visible:
            gc.SetPen(wx.Pen(wx.Colour(128, 255, 0, 255)))
            gc.SetBrush(wx.Brush(wx.Colour(128, 255, 0, 64)))
            for i, field in enumerate(self.fields):
                self.__paint_rect(gc, field)
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
        if self.field_add_mode and self.regions['preview'].Contains(x, y) and ix is not None:
            fields = [field for field in self.fields if field.contains((ix, iy))]
            if fields:
                wx.QueueEvent(self, FieldDeletedEvent(fields[0]))
                return
            capture_mouse(self)
            self.dragging = DRAGGING_RECT
            self.dragging_rect = Rect(left=ix, top=iy, right=ix, bottom=iy)
        else:
            super().on_mouse_down(event)

    def on_mouse_up(self, event):
        if self.image is None:
            return
        if self.dragging == DRAGGING_RECT:
            sz = self.dragging_rect.get_size()
            if abs(sz[0]) >= 8 and abs(sz[1]) >= 8:
                if self.dragging_rect.right < self.dragging_rect.left:
                    self.dragging_rect.left, self.dragging_rect.right = self.dragging_rect.right, self.dragging_rect.left
                if self.dragging_rect.bottom < self.dragging_rect.top:
                    self.dragging_rect.top, self.dragging_rect.bottom = self.dragging_rect.bottom, self.dragging_rect.top
                wx.QueueEvent(self, FieldAddedEvent(self.dragging_rect))
            release_mouse(self)
            self.dragging = DRAGGING_NONE
            self.dragging_rect = None
            self.Refresh()
        else:
            super().on_mouse_up(event)

    def on_mouse_move(self, event):
        if self.image is None:
            return
        if self.dragging == DRAGGING_RECT:
            x = min(max(self.regions['preview'].GetLeft(), event.GetX()), self.regions['preview'].GetRight())
            y = min(max(self.regions['preview'].GetTop(), event.GetY()), self.regions['preview'].GetBottom())
            ix, iy = self.get_image_precise_position(mouse_pos=(x, y))
            ix = min(max(0, int(ix + .5)), self.image.shape[1])
            iy = min(max(0, int(iy + .5)), self.image.shape[0])
            self.dragging_rect.right = ix
            self.dragging_rect.bottom = iy
            self.Refresh()
        else:
            super().on_mouse_move(event)
