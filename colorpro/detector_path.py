"""Unicode-safe model paths for the frozen OpenCV 4.8 Windows reader.

Keep the verified detector and thresholds unchanged. Do not change the process
working directory (other UI workers may be using it), install location or ACLs.
"""

import contextlib
import ctypes
import os
import tempfile
from pathlib import Path


def short_path(path):
    function = ctypes.windll.kernel32.GetShortPathNameW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    function.restype = ctypes.c_uint32
    size = function(str(path), None, 0)
    if not size:
        return None
    buffer = ctypes.create_unicode_buffer(size)
    count = function(str(path), buffer, size)
    return Path(buffer.value) if 0 < count < size else None


def cache_parents():
    yield Path(tempfile.gettempdir())
    # Known Windows folders, not a hard-coded drive or another user's profile.
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 35, None, 0, buffer) == 0:
        yield Path(buffer.value)  # CSIDL_COMMON_APPDATA: shared application-data directory.
    if ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer)):
        yield Path(buffer.value) / "Temp"


@contextlib.contextmanager
def compatible_model_path(path):
    path = Path(path).resolve()
    if os.name != "nt" or str(path).isascii():
        yield path
        return
    # Preserve .onnx: shortening the filename to .ONN breaks OpenCV's format
    # detection even when the shortened full path is otherwise readable.
    parent_alias = short_path(path.parent)
    alias = parent_alias / path.name if parent_alias is not None else None
    if alias is not None and str(alias).isascii():
        yield alias
        return
    # Volumes can have 8.3 names disabled. Use an exclusive, short-lived ASCII
    # directory instead. SourceFaceDetector still verifies the pinned model hash.
    data = path.read_bytes()
    for parent in cache_parents():
        if not str(parent).isascii():
            continue
        try:
            temporary = tempfile.TemporaryDirectory(prefix="ColorPro-model-", dir=parent)
        except OSError:
            continue
        with temporary as folder:
            model = Path(folder) / "yunet.onnx"
            with model.open("xb") as stream:
                stream.write(data)
            yield model
        return
    raise RuntimeError(
        "Не удалось подготовить модель распознавания лиц. "
        "Нет доступной временной папки Windows с латинским путём. "
        "Проверьте права записи в ProgramData или Windows\\Temp."
    )
