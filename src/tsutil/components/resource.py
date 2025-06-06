import wx
from pathlib import Path

class Resource:
    def __init__(self):
        self.bitmap_arrow_up = None
        self.bitmap_arrow_down = None
        self.bitmap_arrow_left = None
        self.bitmap_arrow_right = None

    def get_bitmap_arrow_up(self):
        if not self.bitmap_arrow_up:
            self.bitmap_arrow_up = wx.Bitmap(str(Path(__file__).parent / 'arrow_up.png'), wx.BITMAP_TYPE_PNG)
        return self.bitmap_arrow_up
    
    def get_bitmap_arrow_down(self):
        if not self.bitmap_arrow_down:
            self.bitmap_arrow_down = wx.Bitmap(str(Path(__file__).parent / 'arrow_down.png'), wx.BITMAP_TYPE_PNG)
        return self.bitmap_arrow_down

    def get_bitmap_arrow_left(self):
        if not self.bitmap_arrow_left:
            self.bitmap_arrow_left = wx.Bitmap(str(Path(__file__).parent / 'arrow_left.png'), wx.BITMAP_TYPE_PNG)
        return self.bitmap_arrow_left
    
    def get_bitmap_arrow_right(self):
        if not self.bitmap_arrow_right:
            self.bitmap_arrow_right = wx.Bitmap(str(Path(__file__).parent / 'arrow_right.png'), wx.BITMAP_TYPE_PNG)
        return self.bitmap_arrow_right

resource = Resource()
