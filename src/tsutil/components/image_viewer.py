import wx
import numpy as np
import cv2
from pathlib import Path
from ffio import FrameReader, Probe
from .resource import resource

# MARK: constants

MIN_SIZE = (400, 400)
SCROLL_BAR_SIZE = 12
DRAGGING_NONE = 0
DRAGGING_PREVIEW = 1
DRAGGING_HSCROLL = 2
DRAGGING_VSCROLL = 3
DRAGGING_ZOOM = 4

# MARK: events

myEVT_MOUSE_OVER_IMAGE = wx.NewEventType()
EVT_MOUSE_OVER_IMAGE = wx.PyEventBinder(myEVT_MOUSE_OVER_IMAGE)

class MouseOverImageEvent(wx.ThreadEvent):
    def __init__(self, image_x = None, image_y = None):
        super().__init__(myEVT_MOUSE_OVER_IMAGE)
        self.image_x = image_x
        self.image_y = image_y

# MARK: main class

class ImageViewer(wx.Panel):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.SetMinSize(parent.FromDIP(wx.Size(*MIN_SIZE)))
        self.image = None
        self.image_ox = 0.0
        self.image_oy = 0.0
        self.zoom_ratio = 0.0
        self.min_zoom_ratio = 0.0
        self.zoomed_image = None
        self.dragging = DRAGGING_NONE
        self.dragging_x = 0
        self.dragging_y = 0
        self.dragging_image_ox = 0
        self.dragging_image_oy = 0
        self.buf = None
        self.bitmap = None
        self.regions = {}
        self.bitmap_arrow_down = resource.get_bitmap_arrow_down()
        self.bitmap_arrow_right = resource.get_bitmap_arrow_right()

        self.Bind(wx.EVT_PAINT, self.__on_paint)
        self.Bind(wx.EVT_SIZE, self.__on_size)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.__on_destroy)

        self.Bind(wx.EVT_LEFT_DOWN, self.__on_mouse_down)
        self.Bind(wx.EVT_LEFT_UP, self.__on_mouse_up)
        self.Bind(wx.EVT_MOTION, self.__on_mouse_move)
        self.Bind(wx.EVT_LEAVE_WINDOW, self.__on_mouse_leave)
        self.Bind(wx.EVT_MOUSEWHEEL, self.__on_mouse_wheel)
        self.Bind(wx.EVT_LEFT_DCLICK, self.__on_mouse_double_click)

    def clear(self):
        self.image = None
        self.image_ox = 0
        self.image_oy = 0
        self.zoom_ratio = 0.0
        self.zoomed_image = None
        self.dragging = DRAGGING_NONE
        self.dragging_x = 0
        self.dragging_y = 0
        self.dragging_image_ox = 0
        self.dragging_image_y = 0
        self.__update_preview()

    def set_image(self, image):
        if image is None:
            self.clear()
            return
        if self.image is None:
            self.image_ox = image.shape[1] * .5
            self.image_oy = image.shape[0] * .5
            self.zoom_ratio = 0.0
        self.image = image.copy()
        self.__set_min_zoom_ratio()
        self.__zoom_and_update_preview()
        self.__fire_mouse_over_image()

    def get_image(self):
        return self.image

    def get_image_position(self, mouse_pos=None):
        x, y = self.__get_image_position(mouse_pos=mouse_pos)
        if x is None:
            return None, None
        _x, _y = int(x), int(y)
        return _x, _y
    
    def __get_image_position(self, mouse_pos=None):
        if self.image is None:
            return None, None
        x, y = self.image_ox, self.image_oy
        ox = (self.regions['preview'].GetLeft() + self.regions['preview'].GetRight()) * .5
        oy = (self.regions['preview'].GetTop() + self.regions['preview'].GetBottom()) * .5
        x += (mouse_pos[0] - ox) / self.zoom_ratio
        y += (mouse_pos[1] - oy) / self.zoom_ratio
        if 0 <= x < self.image.shape[1] and 0 <= y < self.image.shape[0]:
            return x, y
        return None, None

    def __set_min_zoom_ratio(self):
        if self.buf is not None and self.image is not None:
            self.min_zoom_ratio = min(self.buf.shape[1] / self.image.shape[1], self.buf.shape[0] / self.image.shape[0])
        else:
            self.min_zoom_ratio = 1.0
        if self.zoom_ratio < self.min_zoom_ratio:
            self.zoom_ratio = self.min_zoom_ratio
            return False
        return True

    def __zoom_and_update_preview(self):
        if self.image is None:
            self.__update_preview()
            return
        h, w = self.image.shape[:2]
        h_new = int(h * self.zoom_ratio)
        w_new = int(w * self.zoom_ratio)
        if self.zoom_ratio > 1.0:
            self.zoomed_image = cv2.resize(self.image, (w_new, h_new), interpolation=cv2.INTER_NEAREST)
        else:
            self.zoomed_image = cv2.resize(self.image, (w_new, h_new), interpolation=cv2.INTER_AREA)
        self.__update_preview()

    def __update_preview(self):
        self.buf[:] = 192
        if self.zoomed_image is None:
            self.bitmap.CopyFromBuffer(self.buf.tobytes())
            self.Refresh()
            return
        buf_h, buf_w = self.buf.shape[:2]
        if buf_w < self.zoomed_image.shape[1]:
            ox_min = buf_w * .5 / self.zoom_ratio
            ox_max = self.image.shape[1] - buf_w * .5 / self.zoom_ratio
            if self.image_ox < ox_min:
                self.image_ox = ox_min
            elif self.image_ox > ox_max:
                self.image_ox = ox_max
        else:
            self.image_ox = self.image.shape[1] * .5
        if buf_h < self.zoomed_image.shape[0]:
            oy_min = buf_h * .5 / self.zoom_ratio
            oy_max = self.image.shape[0] - buf_h * .5 / self.zoom_ratio
            if self.image_oy < oy_min:
                self.image_oy = oy_min
            elif self.image_oy > oy_max:
                self.image_oy = oy_max
        else:
            self.image_oy = self.image.shape[0] * .5
        z_ox = self.image_ox * self.zoom_ratio
        z_oy = self.image_oy * self.zoom_ratio
        buf_h, buf_w = self.buf.shape[:2]
        z_x0 = int(z_ox - (buf_w >> 1) + .5)
        z_y0 = int(z_oy - (buf_h >> 1) + .5)
        z_x1 = z_x0 + buf_w
        z_y1 = z_y0 + buf_h
        if z_x0 < 0:
            b_x0 = -z_x0
            z_x0 = 0
        else:
            b_x0 = 0
        if z_y0 < 0:
            b_y0 = -z_y0
            z_y0 = 0
        else:
            b_y0 = 0
        if z_x1 > self.zoomed_image.shape[1]:
            b_x1 = buf_w - (z_x1 - self.zoomed_image.shape[1])
            z_x1 = self.zoomed_image.shape[1]
        else:
            b_x1 = buf_w    
        if z_y1 > self.zoomed_image.shape[0]:
            b_y1 = buf_h - (z_y1 - self.zoomed_image.shape[0])
            z_y1 = self.zoomed_image.shape[0]
        else:
            b_y1 = buf_h
        self.buf[b_y0:b_y1, b_x0:b_x1, :] = self.zoomed_image[z_y0:z_y0 + (b_y1 - b_y0), z_x0:z_x0 + (b_x1 - b_x0), :]
        self.bitmap.CopyFromBuffer(self.buf.tobytes())
        self.Refresh()

    def __fire_mouse_over_image(self, x = None, y = None):
        if self.image is None:
            wx.QueueEvent(self, MouseOverImageEvent())
        elif x is None:
            wx.QueueEvent(self, MouseOverImageEvent())
        else:
            x, y = self.get_image_position(mouse_pos=(x, y))
            wx.QueueEvent(self, MouseOverImageEvent(x, y))

    def __on_size(self, event):
        size = event.GetSize()
        w, h = size.GetWidth(), size.GetHeight()
        self.buf = np.empty((h - SCROLL_BAR_SIZE, w - SCROLL_BAR_SIZE, 3), dtype=np.uint8)
        self.bitmap = wx.Bitmap.FromBuffer(w - SCROLL_BAR_SIZE, h - SCROLL_BAR_SIZE, self.buf.tobytes())
        self.regions = {
            'preview': wx.Rect(0, 0, self.buf.shape[1], self.buf.shape[0]), 
            'hscroll': wx.Rect(0, self.buf.shape[0], self.buf.shape[1], SCROLL_BAR_SIZE), 
            'vscroll': wx.Rect(self.buf.shape[1], 0, SCROLL_BAR_SIZE, self.buf.shape[0]), 
        }
        if self.__set_min_zoom_ratio():
            self.__update_preview()
        else:
            self.__zoom_and_update_preview()
        self.__fire_mouse_over_image()

    def __on_paint(self, event):
        dc = wx.PaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            bmp_size = self.bitmap.GetSize()
            gc.DrawBitmap(self.bitmap, 0, 0, bmp_size.GetWidth(), bmp_size.GetHeight())
            gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 10)))
            h, w = self.buf.shape[:2]
            gc.DrawRectangle(0, h, w, SCROLL_BAR_SIZE)
            gc.DrawRectangle(w, 0, SCROLL_BAR_SIZE, h)
            if self.image is None:
                return
            gc.SetBrush(wx.Brush(wx.Colour(255, 0, 0, 192)))
            hsl = w / self.zoomed_image.shape[1] * w
            if hsl < w:
                ox = self.image_ox / self.image.shape[1] * w
                hsl_min = max(0, int(ox - hsl * .5 + .5))
                hsl_max = min(w, int(ox + hsl * .5 + .5))
                gc.DrawRectangle(hsl_min, h, hsl_max - hsl_min, SCROLL_BAR_SIZE)
            vsl = h / self.zoomed_image.shape[0] * h
            if vsl < h:
                oy = self.image_oy / self.image.shape[0] * h
                vsl_min = max(0, int(oy - vsl * .5 + .5))
                vsl_max = min(h, int(oy + vsl * .5 + .5))
                gc.DrawRectangle(w, vsl_min, SCROLL_BAR_SIZE, vsl_max - vsl_min)

    def __on_mouse_down(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        h, w = self.buf.shape[:2]
        if self.regions['preview'].Contains(x, y):
            self.dragging = DRAGGING_PREVIEW
            self.dragging_x, self.dragging_y = x, y
            self.dragging_image_ox, self.dragging_image_oy = self.image_ox, self.image_oy
        elif self.regions['hscroll'].Contains(x, y):
            hsl = w / self.zoomed_image.shape[1] * w
            if hsl < w:
                self.dragging = DRAGGING_HSCROLL
                ox = self.image_ox / self.image.shape[1] * w
                hsl_min = max(0, int(ox - hsl * .5 + .5))
                hsl_max = min(w, int(ox + hsl * .5 + .5))
                r = self.regions['hscroll']
                bx = x - r.GetLeft()
                ix = bx / r.GetWidth() * self.image.shape[1]
                if hsl_min <= bx <= hsl_max:
                    self.dragging_x = ix - self.image_ox
                else:
                    self.image_ox = ix
                    self.dragging_x = 0
                    self.__update_preview()
        elif self.regions['vscroll'].Contains(x, y):
            vsl = h / self.zoomed_image.shape[0] * h
            if vsl < h:
                self.dragging = DRAGGING_VSCROLL
                oy = self.image_oy / self.image.shape[0] * h
                vsl_min = max(0, int(oy - vsl * .5 + .5))
                vsl_max = min(h, int(oy + vsl * .5 + .5))
                r = self.regions['vscroll']
                by = y - r.GetTop()
                iy = by / r.GetHeight() * self.image.shape[0]
                if vsl_min <= by <= vsl_max:
                    self.dragging_y = iy - self.image_oy
                else:
                    self.image_oy = iy
                    self.dragging_y = 0
                    self.__update_preview()

    def __on_mouse_up(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        self.dragging = DRAGGING_NONE
        self.dragging_x = 0
        self.dragging_y = 0
        self.dragging_image_ox = 0
        self.dragging_image_y = 0
        if not self.regions['preview'].Contains(x, y):
            self.__fire_mouse_over_image()

    def __on_mouse_move(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        if event.Dragging() and event.LeftIsDown():
            if self.dragging == DRAGGING_PREVIEW:
                dx, dy = (x - self.dragging_x) / self.zoom_ratio, (y - self.dragging_y) / self.zoom_ratio
                self.image_ox = self.dragging_image_ox - dx
                self.image_oy = self.dragging_image_oy - dy
                self.__update_preview()
            elif self.dragging == DRAGGING_HSCROLL:
                r = self.regions['hscroll']
                ix = (x - r.GetLeft()) / r.GetWidth() * self.image.shape[1]
                self.image_ox = ix - self.dragging_x
                self.__update_preview()
            elif self.dragging == DRAGGING_VSCROLL:
                r = self.regions['vscroll']
                iy = (y - r.GetTop()) / r.GetHeight() * self.image.shape[0]
                self.image_oy = iy - self.dragging_y
                self.__update_preview()
        self.__fire_mouse_over_image(x, y)

    def __on_mouse_leave(self, event):
        if self.image is None:
            return
        self.__fire_mouse_over_image()

    def __on_mouse_wheel(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        self.zoom_ratio *= 1.0 + event.GetWheelRotation() * .001
        if self.zoom_ratio < self.min_zoom_ratio:
            self.zoom_ratio = self.min_zoom_ratio
        elif self.zoom_ratio > 2.0:
            self.zoom_ratio = 2.0
        self.__zoom_and_update_preview()
        self.__fire_mouse_over_image(x, y)

    def __on_mouse_double_click(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        if self.regions['preview'].Contains(x, y):
            self.zoom_ratio = 1.0 if self.zoom_ratio != 1.0 else self.min_zoom_ratio
            self.__zoom_and_update_preview()
            self.__fire_mouse_over_image(x, y)

    def __on_destroy(self, event):
        event.Skip()
