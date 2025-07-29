import wx
import numpy as np
import cv2
from pathlib import Path
from ffio import FrameReader, Probe
from .resource import resource
from ..common import *

# MARK: constants

MIN_SIZE = (180, 320)
SCROLL_BAR_SIZE = 12
GRID_SIZE = 50
PROGRESS_BAR_HEIGHT = 10
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

myEVT_MOUSE_CLICK_IMAGE = wx.NewEventType()
EVT_MOUSE_CLICK_IMAGE = wx.PyEventBinder(myEVT_MOUSE_CLICK_IMAGE)

class MouseClickImageEvent(wx.ThreadEvent):
    def __init__(self, image_x = None, image_y = None):
        super().__init__(myEVT_MOUSE_CLICK_IMAGE)
        self.image_x = image_x
        self.image_y = image_y

# MARK: main class

class ImageViewer(wx.Panel):
    def __init__(self, parent, min_size=MIN_SIZE, enable_zoom=True, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.SetMinSize(dpi_aware_size(parent, wx.Size(*min_size)))
        self.SCROLL_BAR_SIZE = dpi_aware(parent, SCROLL_BAR_SIZE)
        self.GRID_SIZE = dpi_aware(parent, GRID_SIZE)
        self.PROGRESS_BAR_HEIGHT = dpi_aware(parent, PROGRESS_BAR_HEIGHT)
        self.enable_zoom = enable_zoom
        size = self.GetSize()
        self.client_width = size.GetWidth()
        self.client_height = size.GetHeight()
        self.image = None
        self.image_ox = 0.0
        self.image_oy = 0.0
        self.zoom_ratio = 0.0
        self.use_grid = False
        self.grid_center_only = False
        self.min_zoom_ratio = 0.0
        self.zoomed_image = None
        self.dragging = DRAGGING_NONE
        self.dragging_x = 0
        self.dragging_y = 0
        self.dragging_image_ox = 0
        self.dragging_image_oy = 0
        self.gesture_zoom = None
        self.progress_total = 0
        self.progress_current = 0
        self.buf = None
        self.bitmap = None
        self.regions = {}
        self.bitmap_arrow_down = resource.get_bitmap_arrow_down()
        self.bitmap_arrow_right = resource.get_bitmap_arrow_right()

        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, self.on_size)

        self.Bind(wx.EVT_LEFT_DOWN, self.on_mouse_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_mouse_up)
        self.Bind(wx.EVT_MOTION, self.on_mouse_move)
        self.Bind(wx.EVT_LEAVE_WINDOW, self.on_mouse_leave)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mouse_wheel)
        zoom_gesture_enabled = self.EnableTouchEvents(wx.TOUCH_ZOOM_GESTURE)
        if enable_zoom:
            if zoom_gesture_enabled:
                self.Bind(wx.EVT_GESTURE_ZOOM, self.on_gesture_zoom)
            self.Bind(wx.EVT_LEFT_DCLICK, self.on_mouse_double_click)

    def set_grid(self, use_grid: bool=True, center_only=False):
        self.use_grid = use_grid
        self.grid_center_only = center_only
        self.Refresh()

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
        self.dragging_image_oy = 0
        self.gesture_zoom = None
        self.progress_total = 0
        self.progress_current = 0
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
        self.fire_mouse_over_image()

    def get_image(self):
        return self.image

    def get_image_position(self, mouse_pos: tuple[int, int]|None=None, range_limit: bool=False) -> tuple[int, int]|tuple[None, None]:
        x, y = self.get_image_precise_position(mouse_pos=mouse_pos)
        if x is None:
            return None, None
        if 0 <= x < self.image.shape[1] and 0 <= y < self.image.shape[0]:
            return int(x), int(y)
        if range_limit:
            x = min(max(0, x), self.image.shape[1] - 1)
            y = min(max(0, y), self.image.shape[0] - 1)
            return int(x), int(y)
        return None, None
    
    def get_image_precise_position(self, mouse_pos: tuple[int, int]|None=None) -> tuple[int, int]|tuple[None, None]:
        if self.image is None or not self.regions['preview'].Contains(mouse_pos[0], mouse_pos[1]):
            return None, None
        x, y = self.image_ox, self.image_oy
        v_ox = (self.regions['preview'].GetLeft() + self.regions['preview'].GetRight()) * .5
        v_oy = (self.regions['preview'].GetTop() + self.regions['preview'].GetBottom()) * .5
        if mouse_pos is not None:
            x += (mouse_pos[0] - v_ox) / self.zoom_ratio
            y += (mouse_pos[1] - v_oy) / self.zoom_ratio
        return x, y

    def set_image_zoom_position(self, image_ox, image_oy, zoom):
        self.zoom_ratio = min(max(self.min_zoom_ratio, zoom), 2.0)
        self.image_ox = image_ox
        self.image_oy = image_oy
        self.__zoom_and_update_preview()

    def get_view_position(self, x: float, y: float) -> tuple[int, int]|tuple[None, None]:
        if self.image is None:
            return None, None
        zx = self.zoomed_image.shape[1] / self.image.shape[1]
        zy = self.zoomed_image.shape[0] / self.image.shape[0]
        ox, oy = self.image_ox, self.image_oy
        v_x = (self.regions['preview'].GetLeft() + self.regions['preview'].GetRight()) * .5
        v_y = (self.regions['preview'].GetTop() + self.regions['preview'].GetBottom()) * .5
        v_x += (x - ox) * zx
        v_y += (y - oy) * zy
        return int(v_x + .5), int(v_y + .5)

    def get_view_rect(self, left: float, top: float, right: float, bottom: float) -> tuple[int, int, int, int]|tuple[None, None, None, None]:
        if self.image is None:
            return None, None, None, None
        zx = self.zoomed_image.shape[1] / self.image.shape[1]
        zy = self.zoomed_image.shape[0] / self.image.shape[0]
        ox, oy = self.image_ox, self.image_oy
        v_x = (self.regions['preview'].GetLeft() + self.regions['preview'].GetRight()) * .5
        v_y = (self.regions['preview'].GetTop() + self.regions['preview'].GetBottom()) * .5
        v_x0 = v_x + (left - ox) * zx
        v_y0 = v_y + (top - oy) * zy
        v_x1 = v_x + (right - ox) * zx
        v_y1 = v_y + (bottom - oy) * zy
        return int(v_x0 + .5), int(v_y0 + .5), int(v_x1 + .5), int(v_y1 + .5)

    def set_progress(self, progress_total, progress_count):
        self.progress_total = progress_total
        self.progress_current = progress_count
        self.Refresh()

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
        zx = self.zoomed_image.shape[1] / self.image.shape[1]
        zy = self.zoomed_image.shape[0] / self.image.shape[0]
        buf_h, buf_w = self.buf.shape[:2]
        if buf_w < self.zoomed_image.shape[1]:
            ox_min = buf_w * .5 / zx
            ox_max = self.image.shape[1] - buf_w * .5 / zx
            if self.image_ox < ox_min:
                self.image_ox = ox_min
            elif self.image_ox > ox_max:
                self.image_ox = ox_max
        else:
            self.image_ox = self.image.shape[1] * .5
        if buf_h < self.zoomed_image.shape[0]:
            oy_min = buf_h * .5 / zy
            oy_max = self.image.shape[0] - buf_h * .5 / zy
            if self.image_oy < oy_min:
                self.image_oy = oy_min
            elif self.image_oy > oy_max:
                self.image_oy = oy_max
        else:
            self.image_oy = self.image.shape[0] * .5
        z_ox = self.image_ox * zx
        z_oy = self.image_oy * zy
        buf_h, buf_w = self.buf.shape[:2]
        z_x0 = int(np.floor(z_ox - buf_w * .5 + .5))    # 負の数は切り捨て処理が必要
        z_y0 = int(np.floor(z_oy - buf_h * .5 + .5))    # 同上
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

    def fire_mouse_over_image(self, x = None, y = None):
        if self.image is None or x is None:
            wx.QueueEvent(self, MouseOverImageEvent())
        else:
            ix, iy = self.get_image_position(mouse_pos=(x, y))
            wx.QueueEvent(self, MouseOverImageEvent(ix, iy))

    def fire_mouse_click_image(self, x = None, y = None):
        if self.image is None or x is None:
            wx.QueueEvent(self, MouseClickImageEvent())
        else:
            ix, iy = self.get_image_position(mouse_pos=(x, y))
            wx.QueueEvent(self, MouseClickImageEvent(ix, iy))

    def on_size(self, event):
        size = event.GetSize()
        self.client_width, self.client_height = size.GetWidth(), size.GetHeight()
        self.buf = np.zeros((self.client_height - self.SCROLL_BAR_SIZE, self.client_width - self.SCROLL_BAR_SIZE, 3), dtype=np.uint8)
        self.bitmap = wx.Bitmap.FromBuffer(self.client_width - self.SCROLL_BAR_SIZE, self.client_height - self.SCROLL_BAR_SIZE, self.buf.tobytes())
        self.regions = {
            'preview': wx.Rect(0, 0, self.buf.shape[1], self.buf.shape[0]), 
            'hscroll': wx.Rect(0, self.buf.shape[0], self.buf.shape[1], self.SCROLL_BAR_SIZE), 
            'vscroll': wx.Rect(self.buf.shape[1], 0, self.SCROLL_BAR_SIZE, self.buf.shape[0]), 
        }
        if self.__set_min_zoom_ratio():
            self.__update_preview()
        else:
            self.__zoom_and_update_preview()
        self.fire_mouse_over_image()

    def on_paint(self, event):
        if self.buf is None:
            return
        dc = wx.BufferedPaintDC(self)
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            gc.SetInterpolationQuality(wx.INTERPOLATION_NONE)
            bmp_size = self.bitmap.GetSize()
            gc.DrawBitmap(self.bitmap, 0, 0, bmp_size.GetWidth(), bmp_size.GetHeight())
            gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 10)))
            h, w = self.buf.shape[:2]
            gc.DrawRectangle(0, h, w, self.SCROLL_BAR_SIZE)
            gc.DrawRectangle(w, 0, self.SCROLL_BAR_SIZE, h)
            if self.image is None:
                return
            gc.SetBrush(wx.Brush(wx.Colour(255, 0, 0, 192)))
            hsl = w / self.zoomed_image.shape[1] * w
            if hsl < w:
                ox = self.image_ox / self.image.shape[1] * w
                hsl_min = max(0, int(ox - hsl * .5 + .5))
                hsl_max = min(w, int(ox + hsl * .5 + .5))
                gc.DrawRectangle(hsl_min, h, hsl_max - hsl_min, self.SCROLL_BAR_SIZE)
            vsl = h / self.zoomed_image.shape[0] * h
            if vsl < h:
                oy = self.image_oy / self.image.shape[0] * h
                vsl_min = max(0, int(oy - vsl * .5 + .5))
                vsl_max = min(h, int(oy + vsl * .5 + .5))
                gc.DrawRectangle(w, vsl_min, self.SCROLL_BAR_SIZE, vsl_max - vsl_min)
            if self.use_grid:
                rgn = self.regions['preview']
                rgn_ox = (rgn.left + rgn.right) // 2
                rgn_oy = (rgn.top + rgn.bottom) // 2
                gc.Clip(wx.Region(rgn))
                gc.SetPen(wx.Pen(wx.Colour(80, 80, 80, 160)))
                gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 0)))
                if self.grid_center_only:
                    gc.DrawRectangle(rgn_ox, rgn.top, .5, rgn.bottom - rgn.top)
                    gc.DrawRectangle(rgn.left, rgn_oy, rgn.right - rgn.left, .5)
                else:
                    for x in range(0, (rgn.right - rgn.left) // 2, self.GRID_SIZE):
                        gc.DrawRectangle(rgn_ox + x, rgn.top, .5, rgn.bottom - rgn.top)
                        if x:
                            gc.DrawRectangle(rgn_ox - x, rgn.top, .5, rgn.bottom - rgn.top)
                    for y in range(0, (rgn.bottom - rgn.top) // 2, self.GRID_SIZE):
                        gc.DrawRectangle(rgn.left, rgn_oy + y, rgn.right - rgn.left, .5)
                        if y:
                            gc.DrawRectangle(rgn.left, rgn_oy - y, rgn.right - rgn.left, .5)
                gc.ResetClip()
            if self.progress_total > 0:
                rgn = self.regions['preview']
                gc.SetBrush(wx.Brush(wx.Colour(64, 64, 64, 255)))
                gc.DrawRectangle(rgn.GetLeft(), rgn.GetBottom() - self.PROGRESS_BAR_HEIGHT, 
                                 rgn.GetWidth(), self.PROGRESS_BAR_HEIGHT)
                gc.SetBrush(wx.Brush(wx.Colour(0, 255, 64, 255)))
                gc.DrawRectangle(rgn.GetLeft() + 1, rgn.GetBottom() - self.PROGRESS_BAR_HEIGHT + 1, 
                                 min(self.progress_current * rgn.GetWidth() // self.progress_total, rgn.GetWidth() - 2), self.PROGRESS_BAR_HEIGHT - 2)

    def on_mouse_down(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        h, w = self.buf.shape[:2]
        if self.regions['preview'].Contains(x, y):
            self.CaptureMouse()
            self.dragging = DRAGGING_PREVIEW
            self.dragging_x, self.dragging_y = x, y
            self.dragging_image_ox, self.dragging_image_oy = self.image_ox, self.image_oy
        elif self.regions['hscroll'].Contains(x, y):
            hsl = w / self.zoomed_image.shape[1] * w
            if hsl < w:
                self.CaptureMouse()
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
                self.CaptureMouse()
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

    def on_mouse_up(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        if self.dragging == DRAGGING_PREVIEW:
            if self.dragging_x == x and self.dragging_y == y:
                self.fire_mouse_click_image(x, y)
            if not self.regions['preview'].Contains(x, y):
                self.fire_mouse_over_image()
        if self.HasCapture():
            self.ReleaseMouse()
        self.dragging = DRAGGING_NONE
        self.dragging_x = 0
        self.dragging_y = 0
        self.dragging_image_ox = 0
        self.dragging_image_oy = 0

    def on_mouse_move(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
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
        self.fire_mouse_over_image(x, y)

    def on_mouse_leave(self, event):
        if self.image is None:
            return
        self.fire_mouse_over_image()

    def on_mouse_wheel(self, event: wx.MouseEvent):
        if self.enable_zoom and event.ControlDown():
            self.on_mouse_wheel_zoom(event)
            return
        if self.image is None:
            return
        axis = event.GetWheelAxis()
        x = event.GetX()
        y = event.GetY()
        rot = event.GetWheelRotation()
        buf_h, buf_w = self.buf.shape[:2]
        if axis == 1:
            self.image_ox += buf_w * .002 * rot / self.zoom_ratio
        else:
            self.image_oy -= buf_h * .002 * rot / self.zoom_ratio
        self.__zoom_and_update_preview()
        self.fire_mouse_over_image(x, y)

    def on_mouse_wheel_zoom(self, event: wx.MouseEvent):
        if self.image is None:
            return
        if event.GetWheelAxis() != 0:
            return
        x = event.GetX()
        y = event.GetY()
        zoom = self.zoom_ratio
        zoom *= 1.0 + event.GetWheelRotation() * .001
        self.zoom_ratio = min(max(self.min_zoom_ratio, zoom), 2.0)
        self.__zoom_and_update_preview()
        self.fire_mouse_over_image(x, y)

    def on_gesture_zoom(self, event: wx.ZoomGestureEvent):
        if self.image is None:
            return
        pos = event.GetPosition()
        if event.IsGestureStart():
            self.gesture_zoom = self.zoom_ratio
        if self.gesture_zoom is not None:
            zoom = self.gesture_zoom
            zoom *= event.GetZoomFactor()
            self.zoom_ratio = min(max(self.min_zoom_ratio, zoom), 2.0)
            self.__zoom_and_update_preview()
            self.fire_mouse_over_image(pos.x, pos.y)
        if event.IsGestureEnd():
            self.gesture_zoom = None

    def on_mouse_double_click(self, event):
        if self.image is None:
            return
        x = event.GetX()
        y = event.GetY()
        if self.regions['preview'].Contains(x, y):
            self.zoom_ratio = 1.0 if self.zoom_ratio != 1.0 else self.min_zoom_ratio
            self.__zoom_and_update_preview()
            self.fire_mouse_over_image(x, y)
