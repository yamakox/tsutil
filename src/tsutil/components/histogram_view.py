import wx
import numpy as np
import matplotlib.pyplot as plt
import io
from PIL import Image
from numba import njit
from ..common import *

# MARK: constants

MIN_SIZE = (400, 80)

# MARK: functions

@njit
def _compute_hist(frame, hist):
    #hist = np.zeros((256, 3))
    for i in range(frame.shape[0]):
        for j in range(frame.shape[1]):
            hist[frame[i, j, 0], 0] += 1
            hist[frame[i, j, 1], 1] += 1
            hist[frame[i, j, 2], 2] += 1

# MARK: main class

class HistogramView(wx.Panel):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        #self.SetMinSize(dpi_aware_size(parent, wx.Size(*MIN_SIZE)))
        self.SetSizeHints(dpi_aware_size(parent, wx.Size(*MIN_SIZE)))
        self.SetBackgroundColour(wx.Colour(0, 0, 0))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.hist = np.zeros((256, 3), dtype=np.int64)
        self.bitmap = None

        self.Bind(wx.EVT_PAINT, self.__on_paint)
        self.Bind(wx.EVT_SIZE, self.__on_size)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.__on_destroy)

    def clear(self):
        self.hist[:] = 0
        self.bitmap = None
        self.Refresh()

    def begin_histogram(self):
        self.hist[:] = 0

    def add_histogram(self, frame):
        #for i in range(3):
        #    self.hist[:, i] += np.histogram(frame[:, :, i], bins=256, range=(0, 256))[0]
        _compute_hist(frame, self.hist)

    def end_histogram(self):
        interp = (self.hist[:-2, :] + self.hist[2:, :]) * .5
        interp = np.pad(interp, ((1, 1), (0, 0)), mode='constant', constant_values=0)
        self.hist[self.hist == 0] = interp[self.hist == 0]

    def update_view(self):
        size = self.GetSize()
        if size.GetWidth() == 0 or size.GetHeight() == 0:
            return
        my_dpi=100
        x = np.arange(0, 256)
        charts = []
        for ch, colors in enumerate((
            ((.5, 0, 0), (1, 0, 0)), 
            ((0, .5, 0), (0, 1, 0)), 
            ((0, 0, .5), (0, 0, 1)), 
        )):
            fig = plt.figure(figsize=(size.GetWidth()/my_dpi, size.GetHeight()/my_dpi), dpi=my_dpi, facecolor='#000000')
            ax = fig.add_axes([0, 0, .99, 1])  # left, bottom, width, height（余白ゼロ）
            ax.set_facecolor('#000000')
            ax.fill_between(x, self.hist[:, ch], color=colors[0])
            ax.plot(x, self.hist[:, ch], color=colors[1], linewidth=1.2)
            plt.axis('off')
            ax.set_xlim([0, 255])
            ax.set_ylim([0, max(1,np.max(self.hist[:, ch])*1.01)])
            #fig.canvas.draw()
            #_w, _h = fig.canvas.get_width_height()
            #charts.append(np.frombuffer(fig.canvas.buffer_rgba(), np.uint8).reshape(_h, _w, -1).copy())
            png = io.BytesIO()
            plt.savefig(png, dpi=my_dpi, transparent=False, bbox_inches='tight', pad_inches=0)
            charts.append(np.asarray(Image.open(png)))
            plt.close()
        # スクリーン合成の式 c = a + b - a * b (0 <= a, b <= 1) の第3項は0になるため計算不要
        merged = charts[0][:, :, :3] + charts[1][:, :, :3] + charts[2][:, :, :3]
        self.bitmap = wx.Bitmap.FromBuffer(merged.shape[1], merged.shape[0], merged.tobytes())
        self.Refresh()

    def __on_size(self, event):
        self.update_view()

    def __on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            if self.bitmap is not None:
                bmp_size = self.bitmap.GetSize()
                sz = self.GetSize()
                gc.DrawBitmap(self.bitmap, (sz.GetWidth() - bmp_size.GetWidth()) // 2, (sz.GetHeight() - bmp_size.GetHeight()) // 2, bmp_size.GetWidth(), bmp_size.GetHeight())

    def __on_destroy(self, event):
        event.Skip()
