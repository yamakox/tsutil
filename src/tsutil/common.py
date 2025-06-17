from pathlib import Path
from pydantic import BaseModel

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

# MARK: common models

class Point(BaseModel):
    x: int|None = None
    y: int|None = None

    def __str__(self) -> str:
        return f'({self.x},{self.y})'
        #if None in [self.x, self.y]:
        #    return f'({self.x}, {self.y})'
        #return f'({self.x:4d}, {self.y:4d})'

    def to_tuple(self):
        return self.x, self.y

class Rect(BaseModel):
    left: int|None = None
    top: int|None = None
    right: int|None = None
    bottom: int|None = None

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

    def __str__(self) -> str:
        return f'{self.left_top}-{self.right_top}-{self.right_bottom}-{self.left_bottom}'

