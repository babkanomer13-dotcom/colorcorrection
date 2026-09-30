"""Bounded, non-destructive image/ZIP input and transactional output."""

from __future__ import annotations

import contextlib
import hashlib
import io
import math
import os
import re
import stat
import tempfile
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
from PIL import Image, ImageCms, ImageOps

from colorcorrection.imageio import _convert_to_srgb
from colorpro.safety import validate_output_parent

RAW_EXTENSIONS = set()

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"} | RAW_EXTENSIONS
MAX_FILE = 256 * 1024 * 1024
MAX_PIXELS = 80_000_000
MAX_ITEMS = 10_000
MAX_EXPANDED = 100 * 1024**3


@dataclass(frozen=True)
class InputItem:
    path: str
    size: int
    mtime_ns: int
    member: str = ""
    header_offset: int = -1
    member_size: int = 0
    crc: int = 0

    @property
    def name(self):
        return PurePosixPath(self.member).name if self.member else Path(self.path).name

    @property
    def label(self):
        return f"{Path(self.path).name} / {self.member}" if self.member else self.name

    @property
    def key(self):
        return (os.path.normcase(self.path), self.member, self.header_offset)

    def unchanged(self):
        info = Path(self.path).stat()
        if info.st_size != self.size or info.st_mtime_ns != self.mtime_ns:
            raise ValueError("Исходник изменился после добавления. Добавьте его заново.")


def safe_member(info):
    name = info.orig_filename
    parts = PurePosixPath(name).parts
    if (
        not parts
        or name.startswith(("/", "\\"))
        or "\\" in name
        or any(p in {"..", "."} or ":" in p or "\x00" in p for p in parts)
    ):
        raise ValueError("Небезопасный путь внутри ZIP")
    if stat.S_ISLNK(info.external_attr >> 16):
        raise ValueError("Ссылки внутри ZIP не поддерживаются")
    if info.flag_bits & 1:
        raise ValueError("ZIP с паролем не поддерживается")
    if info.file_size > MAX_FILE or info.file_size / max(1, info.compress_size) > 300:
        raise ValueError("Превышен безопасный размер или коэффициент сжатия ZIP")


def collect_inputs(paths, existing=(), cancelled=lambda: False):
    items, errors = [], []
    seen = {item.key for item in existing}
    for value in paths:
        if cancelled():
            break
        path = Path(value).resolve()
        try:
            if not path.is_file():
                raise ValueError("Выберите файл, а не папку")
            info = path.stat()
            if path.suffix.lower() == ".zip":
                with zipfile.ZipFile(path) as archive:
                    entries = archive.infolist()
                    if len(entries) > MAX_ITEMS or sum(i.file_size for i in entries) > MAX_EXPANDED:
                        raise ValueError("Слишком большой ZIP: максимум 10 000 записей / 100 ГБ")
                    added = 0
                    for entry in entries:
                        if cancelled():
                            break
                        if (
                            entry.is_dir()
                            or PurePosixPath(entry.filename).suffix.lower() not in EXTENSIONS
                        ):
                            continue
                        try:
                            safe_member(entry)
                            item = InputItem(
                                str(path),
                                info.st_size,
                                info.st_mtime_ns,
                                entry.filename,
                                entry.header_offset,
                                entry.file_size,
                                entry.CRC,
                            )
                            if item.key not in seen:
                                if len(seen) >= MAX_ITEMS:
                                    raise ValueError("Очередь ограничена 10 000 фотографиями")
                                seen.add(item.key)
                                items.append(item)
                                added += 1
                        except ValueError as error:
                            errors.append(f"{path.name} / {entry.filename}: {error}")
                    if not added and not any(i.path == str(path) for i in existing):
                        errors.append(f"{path.name}: новых поддерживаемых фотографий нет")
            else:
                if path.suffix.lower() not in EXTENSIONS:
                    raise ValueError("Поддерживаются JPEG, PNG, WebP, TIFF, BMP и ZIP")
                if info.st_size > MAX_FILE:
                    raise ValueError("Файл больше 256 МБ")
                item = InputItem(str(path), info.st_size, info.st_mtime_ns)
                if item.key not in seen:
                    if len(seen) >= MAX_ITEMS:
                        raise ValueError("Очередь ограничена 10 000 фотографиями")
                    seen.add(item.key)
                    items.append(item)
        except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError) as error:
            errors.append(f"{path.name}: {error}")
    return items, errors


@contextlib.contextmanager
def input_stream(item):
    item.unchanged()
    if not item.member:
        with open(item.path, "rb") as stream:
            yield stream
    else:
        with zipfile.ZipFile(item.path) as archive:
            info = next(
                (i for i in archive.infolist() if i.header_offset == item.header_offset), None
            )
            if info is None or (info.filename, info.file_size, info.CRC) != (
                item.member,
                item.member_size,
                item.crc,
            ):
                raise ValueError("Состав ZIP изменился")
            safe_member(info)
            # Never extract member paths. At most one image in an auto-deleted temp file.
            with tempfile.SpooledTemporaryFile(max_size=16 * 1024**2, mode="w+b") as temp:
                total = 0
                with archive.open(info) as source:
                    while chunk := source.read(1024**2):
                        total += len(chunk)
                        if total > MAX_FILE or total > info.file_size:
                            raise ValueError("ZIP превышает заявленный размер")
                        temp.write(chunk)
                temp.seek(0)
                yield temp
    item.unchanged()


def read_image(item):
    with input_stream(item) as stream, warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        header = stream.read(32)
        stream.seek(0)
        if header.startswith(b"\x89PNG") and len(header) > 24 and header[24] == 16:
            raise ValueError("16-битный PNG: сначала экспортируйте 8-битный RGB")
        with Image.open(stream) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("Фото больше 80 мегапикселей")
            # Some real camera JPEGs carry MPF auxiliary images and Pillow calls
            # them MPO. V39 has always consumed the primary full-resolution frame.
            # Do not treat an auxiliary depth/thumbnail image as another input.
            container_note = None
            if image.format == "MPO":
                image.seek(0)
                container_note = "MPO: processed primary frame 0 only; original container unchanged"
            elif getattr(image, "n_frames", 1) != 1:
                raise ValueError("Многостраничные / анимированные изображения не поддерживаются")
            if image.format == "TIFF" and max(image.tag_v2.get(258, (8,))) > 8:
                raise ValueError("16-битный TIFF: сначала экспортируйте 8-битный RGB")
            if image.mode not in {"RGB", "L"}:
                raise ValueError(f"Режим {image.mode}: нужен непрозрачный 8-битный RGB или L")
            icc = image.info.get("icc_profile")
            with ImageOps.exif_transpose(image) as normalized:
                safe = Image.Exif()
                original = normalized.getexif()
                for tag in (271, 272, 306, 33434, 33437, 34855, 36867, 36868, 37386, 42036):
                    value = original.get(tag)
                    if isinstance(value, (int, float, str)) and len(str(value)) < 512:
                        safe[tag] = value
                safe[274] = 1
                safe[40961] = 1
                safe[40962], safe[40963] = normalized.size
                with _convert_to_srgb(normalized, icc) as converted:
                    rgb = np.asarray(converted, dtype=np.uint8).copy()
                metadata = {
                    "icc_profile": ImageCms.ImageCmsProfile(
                        ImageCms.createProfile("sRGB")
                    ).tobytes(),
                    "exif": safe.tobytes(),
                }
                if container_note:
                    metadata["container_note"] = container_note
                dpi = image.info.get("dpi")
                if isinstance(dpi, tuple) and len(dpi) == 2:
                    if all(
                        isinstance(v, (int, float)) and math.isfinite(v) and 1 <= v <= 9600
                        for v in dpi
                    ):
                        metadata["dpi"] = dpi
        stream.seek(0)
        hasher = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
        digest = hasher.hexdigest()
    return rgb, metadata, digest


def output_name(number, item, fmt):
    forbidden = re.escape('<>:"/|?*' + chr(92))
    stem = re.sub("[" + forbidden + r"\x00-\x1f]", "_", Path(item.name).stem)
    stem = stem.strip(" .")[:100] or "photo"
    return f"{number:05d}_{stem}_color.{'jpg' if fmt == 'JPEG' else 'png'}"


def save_result(path, pixels, metadata, fmt):
    path = Path(path)
    validate_output_parent(path.parent)
    if path.exists():
        raise FileExistsError("Результат уже существует; перезапись запрещена")
    temp = path.with_suffix(path.suffix + ".partial")
    options = {k: v for k, v in metadata.items() if k in {"icc_profile", "exif", "dpi"} and v}
    options.update(quality=100, subsampling=0) if fmt == "JPEG" else options.update(
        compress_level=3
    )
    created = False
    try:
        with temp.open("xb") as stream:
            created = True
            Image.fromarray(pixels).save(stream, format=fmt, **options)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows rename refuses to replace an existing destination.
        temp.rename(path)
    finally:
        if created and temp.exists():
            temp.unlink()


def preview_bytes(pixels):
    image = Image.fromarray(pixels)
    image.thumbnail((1500, 1500))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()
