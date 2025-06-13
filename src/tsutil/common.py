from pathlib import Path

# MARK: constants

APP_NAME = "tsutil"
MOVIE_FILE_SUFFIX = ['.mp4', '.mov', '.m4v']
MOVIE_FILE_WILDCARD = 'Movie files (*.mp4;*.mov;*.m4v)|*.mp4;*.mov;*.m4v'
IMAGE_CATALOG_FILE_SUFFIX = ['.txt', '.lst']
IMAGE_CATALOG_FILE_WILDCARD = 'Image catalog files (*.txt;*.lst)|*.txt;*.lst'

# utilities

def get_path(path: str) -> Path:
    if not path:
        return None
    return Path(path)

def path_exists(path: Path) -> bool:
    return path and path.exists()
