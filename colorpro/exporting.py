"""Explicit image export. Never overwrite an input or an unowned destination."""

import os
import tempfile
from pathlib import Path

from PIL import Image

from colorpro.files import output_name, save_result, source_stem
from colorpro.levels import digest
from colorpro.safety import validate_output_parent


def export_folder(item, mode, custom):
    if mode not in {"beside", "custom"}:
        raise ValueError("Неизвестный режим сохранения")
    if mode == "custom":
        return validate_output_parent(custom)
    parent = Path(item.path).resolve().parent
    # If an exported photo is deliberately opened, do not create ColorPro/ColorPro.
    folder = parent if parent.name.casefold() == "colorpro" else parent / "ColorPro"
    return validate_output_parent(folder)


def export_name(item, fmt):
    safe = output_name(item, fmt)
    stem = Path(safe).stem
    suffix = Path(item.name).suffix
    if (fmt == "JPEG" and suffix.lower() in {".jpg", ".jpeg"}) or (
        fmt == "PNG" and suffix.lower() == ".png"
    ):
        return stem + suffix
    return stem + Path(safe).suffix


def export_photo(
    item,
    pixels,
    metadata,
    fmt,
    mode,
    custom,
    protected=(),
    previous=None,
    registry=None,
):
    item.unchanged()
    folder = export_folder(item, mode, custom)
    folder.mkdir(parents=True, exist_ok=True)
    forbidden = {Path(p).resolve() for p in protected} | {Path(item.path).resolve()}
    target = folder / export_name(item, fmt)
    expected = None
    owned = None
    if previous and previous.get("output") and previous.get("export_sha256"):
        old = Path(previous["output"])
        parents = old.parent.resolve()
        owned_folder = parents == folder or (
            parents.parent == folder and parents.name.isdigit()
        )
        legacy_names = {
            source_stem(item) + target.suffix,
            source_stem(item) + "_с" + Path(output_name(item, fmt)).suffix,
        }
        if owned_folder and old.name in legacy_names | {target.name}:
            owned, expected = old, previous["export_sha256"]
            target = old.with_name(target.name)
    if target != owned:
        number = 1
        while target.exists() or target.resolve() in forbidden:
            number += 1
            target = folder / str(number) / export_name(item, fmt)
    if target.is_symlink() or target.resolve() in forbidden:
        raise ValueError("Нельзя перезаписывать исходную фотографию")
    target.parent.mkdir(parents=True, exist_ok=True)
    if owned is not None:
        if owned.is_symlink() or owned.resolve() in forbidden:
            raise ValueError("Нельзя перезаписывать исходную фотографию")
        if not owned.is_file() or digest(owned) != expected:
            raise ValueError("Результат изменён другой программой. Экспорт отменён.")
    with tempfile.TemporaryDirectory(
        prefix=".colorpro-export-", dir=target.parent
    ) as temp:
        encoded = Path(temp) / target.name
        save_result(encoded, pixels, metadata, fmt)
        with Image.open(encoded) as image:
            image.load()
            if image.size != (pixels.shape[1], pixels.shape[0]):
                raise ValueError("Проверка экспортированной фотографии не пройдена")
        checksum = digest(encoded)
        item.unchanged()
        if registry is not None:
            registry.remember_export(target, checksum)
        if owned is not None:
            if digest(owned) != expected or owned.is_symlink():
                raise ValueError("Файл изменился во время экспорта")
            # Migrate a verified export from an older version without leaving
            # another image behind. Windows rename never replaces a collision.
            if owned != target:
                owned.rename(target)
            try:
                os.replace(encoded, target)
            except OSError:
                if owned != target:
                    target.rename(owned)
                raise
        else:
            encoded.rename(target)  # Windows refuses a racing/unowned destination.
    return {"output": str(target), "export_sha256": checksum}
