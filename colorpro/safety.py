"""Protect archive roots even when selected through a junction or edited textbox."""

import os
from pathlib import Path

from colorpro.config import load_config


def validate_output_parent(value, protected_roots=None):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Укажите полный путь к папке результатов")
    path = path.resolve()
    if not path.name or str(path).startswith(("\\\\", "//")):
        raise ValueError("Выберите отдельную локальную папку, не корень диска")
    if os.name == "nt":
        import ctypes

        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
            raise ValueError("Сетевые папки для результатов не поддерживаются")
    roots = protected_roots if protected_roots is not None else load_config()["protected_roots"]
    for root in roots:
        try:
            path.relative_to(Path(root).resolve())
        except ValueError:
            continue
        raise ValueError("Архив защищён от записи. Выберите другую папку результатов.")
    return path
