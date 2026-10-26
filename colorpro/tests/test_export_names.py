"""Output naming, previous-version migration, and image ownership."""

import os
from pathlib import Path

import pytest
from PIL import Image

from colorpro.exporting import export_name, export_photo
from colorpro.files import InputItem, collect_inputs, output_name, read_image
from colorpro.levels import digest


@pytest.mark.parametrize(
    "name,fmt,expected",
    [
        ("IMG_2362.JPG", "JPEG", "IMG_2362_СС.JPG"),
        ("Портрет.jpeg", "JPEG", "Портрет_СС.jpeg"),
        ("Портрет.png", "JPEG", "Портрет_СС.jpg"),
        ("IMG_2362.JPG", "PNG", "IMG_2362_СС.png"),
        ("Портрет_СС.png", "PNG", "Портрет_СС.png"),
        ("Портрет_СС_сс.png", "PNG", "Портрет_СС.png"),
    ],
)
def test_export_suffix_for_files_and_zip(name, fmt, expected):
    for item in (
        InputItem(name, 0, 0),
        InputItem("photos.zip", 0, 0, "folder/" + name),
    ):
        assert export_name(item, fmt) == expected
        assert Path(output_name(item, fmt)).stem == Path(expected).stem


def legacy_export(tmp_path, name="photo.png"):
    source = tmp_path / "photo.png"
    Image.new("RGB", (20, 30), (100, 120, 140)).save(source)
    item = collect_inputs([source])[0][0]
    folder = tmp_path / "ColorPro"
    folder.mkdir()
    old = folder / name
    Image.new("RGB", (20, 30), (110, 130, 150)).save(old)
    pixels, metadata, _ = read_image(item)
    previous = {"output": str(old), "export_sha256": digest(old)}
    return item, pixels, metadata, previous


@pytest.mark.parametrize("name", ["photo.png", "photo_с.png", "photo_СС.png"])
def test_repeat_export_migrates_owned_result_without_duplicate(tmp_path, name):
    item, pixels, metadata, previous = legacy_export(tmp_path, name)
    original = Path(item.path).read_bytes()
    for step in range(3):
        previous = export_photo(
            item, pixels + step, metadata, "PNG", "beside", "", previous=previous
        )
        assert Path(previous["output"]).name == "photo_СС.png"
        assert list((tmp_path / "ColorPro").rglob("*.png")) == [
            Path(previous["output"])
        ]
    assert Path(item.path).read_bytes() == original


def test_migration_keeps_unowned_destination_and_refuses_changed_previous(tmp_path):
    item, pixels, metadata, previous = legacy_export(tmp_path)
    occupied = tmp_path / "ColorPro/photo_СС.png"
    occupied.write_bytes(b"another photo")
    old = Path(previous["output"])
    old.write_bytes(b"external edit")
    with pytest.raises(ValueError, match="другой программой"):
        export_photo(item, pixels, metadata, "PNG", "beside", "", previous=previous)
    previous["export_sha256"] = digest(old)
    result = export_photo(
        item, pixels, metadata, "PNG", "beside", "", previous=previous
    )
    assert Path(result["output"]) == tmp_path / "ColorPro/2/photo_СС.png"
    assert not old.exists() and occupied.read_bytes() == b"another photo"


def test_failed_replace_restores_old_name_and_bytes(tmp_path, monkeypatch):
    item, pixels, metadata, previous = legacy_export(tmp_path)
    old = Path(previous["output"])
    before = old.read_bytes()

    def fail(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError):
        export_photo(item, pixels, metadata, "PNG", "beside", "", previous=previous)
    assert old.read_bytes() == before
    assert list(old.parent.iterdir()) == [old]
