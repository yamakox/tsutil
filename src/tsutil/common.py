from pathlib import Path
from pydantic import BaseModel
import numpy as np
import cv2

# MARK: constants

APP_NAME = "tsutil"
MOVIE_FILE_SUFFIX = ['.mp4', '.mov', '.m4v']
MOVIE_FILE_WILDCARD = 'Movie files (*.mp4;*.mov;*.m4v)|*.mp4;*.mov;*.m4v'
IMAGE_CATALOG_FILE_SUFFIX = ['.txt', '.lst']
IMAGE_CATALOG_FILE_WILDCARD = 'Image catalog files (*.txt;*.lst)|*.txt;*.lst'

# MARK: utility functions

def get_path(path: str) -> Path:
    if not path:
        return None
    return Path(path)

def path_exists(path: Path) -> bool:
    return path and path.exists()


def get_spin_ctrl_value(spin_ctrl):
    value = spin_ctrl.GetTextValue()
    if len(value) == 0:
        return spin_ctrl.GetValue()
    _min, _max = spin_ctrl.GetMin(), spin_ctrl.GetMax()
    if type(_min) == int:
        value = int(value)
    else:
        value = float(value)
    return min(max(_min, value), _max)


# MARK: common models

class Point(BaseModel):
    x: int|None = None
    y: int|None = None

    def __str__(self) -> str:
        return f'({self.x},{self.y})'
        #if None in [self.x, self.y]:
        #    return f'({self.x}, {self.y})'
        #return f'({self.x:4d}, {self.y:4d})'

    def clear(self):
        self.x = None
        self.y = None

    def copy_from(self, other: 'Point'):
        self.x = other.x
        self.y = other.y

    def is_none(self):
        return self.x is None or self.y is None

    def init(self, x, y):
        self.x = x
        self.y = y

    def to_tuple(self):
        return self.x, self.y

class Rect(BaseModel):
    left: int|None = None
    top: int|None = None
    right: int|None = None
    bottom: int|None = None

    def clear(self):
        self.left = None
        self.top = None
        self.right = None
        self.bottom = None

    def copy_from(self, other: 'Rect'):
        self.left = other.left
        self.top = other.top
        self.right = other.right
        self.bottom = other.bottom

    def is_none(self):
        return self.left is None or self.top is None or self.right is None or self.bottom is None

    def init(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def __str__(self) -> str:
        x, y = self.get_center()
        w, h = self.get_size()
        return f'({x},{y}) {w}x{h}'
        #if x is None:
        #    return '(None, None) None x None'
        #return f'({x:4d}, {y:4d}) {w:4d} x {h:4d}'

    def to_tuple(self) -> tuple[int|None, int|None, int|None, int|None]:
        return self.left, self.top, self.right, self.bottom

    def get_center(self) -> tuple[int|None, int|None]:
        if None in [self.left, self.top, self.right, self.bottom]:
            return None, None
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    def get_size(self) -> tuple[int|None, int|None]:
        if None in [self.left, self.top, self.right, self.bottom]:
            return None, None
        return (self.right - self.left), (self.bottom - self.top)

class PerspectivePoints(BaseModel):
    left_top: Point = Point()
    right_top: Point = Point()
    right_bottom: Point = Point()
    left_bottom: Point = Point()

    def clear(self):
        self.left_top.clear()
        self.right_top.clear()
        self.right_bottom.clear()
        self.left_bottom.clear()

    def copy_from(self, other: 'PerspectivePoints'):
        self.left_top.copy_from(other.left_top)
        self.right_top.copy_from(other.right_top)
        self.right_bottom.copy_from(other.right_bottom)
        self.left_bottom.copy_from(other.left_bottom)

    def is_none(self):
        return (
            self.left_top.is_none() or 
            self.right_top.is_none() or 
            self.right_bottom.is_none() or 
            self.left_bottom.is_none()
        )

    def init(self, frame: np.ndarray):
        h, w = frame.shape[:2]
        self.left_top.init(0, 0)
        self.right_top.init(w, 0)
        self.right_bottom.init(w, h)
        self.left_bottom.init(0, h)

    def left_limit(self):
        return max(self.left_top.x, self.left_bottom.x)

    def top_limit(self):
        return max(self.left_top.y, self.right_top.y)

    def right_limit(self):
        return min(self.right_top.x, self.right_bottom.x)

    def bottom_limit(self):
        return min(self.left_bottom.y, self.right_bottom.y)

    def get_transform_matrix(self):
        l = self.left_limit()
        t = self.top_limit()
        r = self.right_limit()
        b = self.bottom_limit()
        return cv2.getPerspectiveTransform(
            np.float32([
                self.left_top.to_tuple(), 
                self.right_top.to_tuple(), 
                self.right_bottom.to_tuple(), 
                self.left_bottom.to_tuple(), 
            ]), 
            np.float32([
                [l, t], 
                [r, t], 
                [r, b], 
                [l, b], 
            ])
        )

    def __str__(self) -> str:
        return f'{self.left_top}-{self.right_top}-{self.right_bottom}-{self.left_bottom}'

