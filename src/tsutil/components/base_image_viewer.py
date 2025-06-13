from .image_viewer import ImageViewer

class BaseImageViewer(ImageViewer):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
