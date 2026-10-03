from __future__ import annotations

import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from scripts.check_public_repo import (
    MAX_FILE_BYTES,
    inspect_file,
    is_synthetic_fixture,
    scan_pushed_commits,
    scan_repository,
)


def _rules(path: str, data: bytes, *, declared_size: int | None = None) -> set[str]:
    return {item.rule for item in inspect_file(path, data, declared_size=declared_size)}


def _png(width: int = 2, height: int = 2, *, exif: bool = False) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    result = b"\x89PNG\r\n\x1a\n"
    result += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    if exif:
        result += chunk(b"eXIf", b"MM\x00*")
    result += chunk(b"IDAT", zlib.compress(rows))
    result += chunk(b"IEND", b"")
    return result


def _git(repo: Path, *arguments: str) -> None:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("git executable is required for this integration test")
    subprocess.run(  # noqa: S603 - controlled test arguments, no shell
        [executable, *arguments],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def _git_output(repo: Path, *arguments: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("git executable is required for this integration test")
    process = subprocess.run(  # noqa: S603 - controlled test arguments, no shell
        [executable, *arguments],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return process.stdout.decode("ascii").strip()


def test_only_designated_fixture_tree_is_synthetic() -> None:
    assert is_synthetic_fixture("tests/fixtures/synthetic/gradient.png")
    assert not is_synthetic_fixture("tests/fixtures/gradient.png")
    assert not is_synthetic_fixture("docs/synthetic/example.png")


def test_small_metadata_free_synthetic_png_is_allowed() -> None:
    assert _rules("tests/fixtures/synthetic/gradient.png", _png()) == set()


def test_photo_outside_synthetic_tree_is_blocked() -> None:
    assert "private-photo" in _rules("examples/portrait.jpg", b"not a real image")


def test_only_exact_reviewed_branding_is_allowed() -> None:
    name = "colorpro/assets/logo.png"
    artwork = Path(__file__).resolve().parents[1] / name
    assert not _rules(name, artwork.read_bytes())
    assert "private-photo" in _rules(name, _png())
    assert "private-photo" in _rules("colorpro/assets/photo.png", artwork.read_bytes())


def test_photo_signature_cannot_be_hidden_behind_text_extension() -> None:
    disguised_jpeg = b"\xff\xd8\xff\xe0" + b"private image payload"

    assert "private-photo" in _rules("notes.dat", disguised_jpeg)
    assert "unsafe-synthetic-image" in _rules(
        "tests/fixtures/synthetic/not-an-array.npy",
        disguised_jpeg,
    )


def test_synthetic_photo_must_be_small_and_metadata_free() -> None:
    oversized = _rules(
        "tests/fixtures/synthetic/large.png",
        _png(),
        declared_size=MAX_FILE_BYTES + 1,
    )
    metadata = _rules("tests/fixtures/synthetic/exif.png", _png(exif=True))
    dimensions = _rules("tests/fixtures/synthetic/wide.png", _png(width=513, height=1))

    assert {"large-file", "unsafe-synthetic-image"} <= oversized
    assert "unsafe-synthetic-image" in metadata
    assert "unsafe-synthetic-image" in dimensions


def test_model_weight_is_blocked_even_in_synthetic_tree() -> None:
    rules = _rules("tests/fixtures/synthetic/tiny.safetensors", b"synthetic")
    assert "model-weight" in rules


@pytest.mark.parametrize(
    "contents, expected_rule",
    [
        ("api_key = " + "a" * 32, "generic-secret"),
        ("token = " + "ghp_" + "A" * 36, "github-token"),
        ("key = " + "sk-" + "B" * 32, "openai-key"),
        ("-----BEGIN " + "PRIVATE KEY-----", "private-key"),
    ],
)
def test_secret_patterns_are_blocked(contents: str, expected_rule: str) -> None:
    assert expected_rule in _rules("config.txt", contents.encode())


def test_explicit_placeholders_are_allowed() -> None:
    contents = b'api_key = "your_api_key_here"\npassword = "change-me"\n'
    assert "generic-secret" not in _rules(".env.example", contents)


@pytest.mark.parametrize(
    "private_path",
    [
        "C:" + "\\" + "Users" + "\\" + "person" + "\\" + "archive",
        "E:" + "\\" + "Albums" + "\\" + "Season 2025-2026",
        "/" + "home/person/archive",
        "\\" + "\\" + "server" + "\\" + "private-share" + "\\" + "photos",
    ],
)
def test_machine_specific_absolute_paths_are_blocked(private_path: str) -> None:
    rules = _rules("settings.yaml", f"archive: {private_path}\n".encode())
    assert "absolute-private-path" in rules


def test_staged_scan_reads_index_instead_of_working_tree(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "guard@example.invalid")
    _git(tmp_path, "config", "user.name", "Guard Test")
    config = tmp_path / "settings.txt"
    secret = "pass" + "word = " + "correct-horse-battery-staple"
    config.write_text(secret, encoding="utf-8")
    _git(tmp_path, "add", "settings.txt")
    config.write_text("password = change-me\n", encoding="utf-8")

    staged = scan_repository(tmp_path, staged_only=True)
    working_tree = scan_repository(tmp_path, paths=["settings.txt"])

    assert "generic-secret" in {item.rule for item in staged}
    assert "generic-secret" not in {item.rule for item in working_tree}


def test_tracked_scan_rejects_real_photo(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--quiet")
    photo = tmp_path / "portrait.jpg"
    photo.write_bytes(b"private image bytes")
    _git(tmp_path, "add", "portrait.jpg")

    findings = scan_repository(tmp_path)

    assert "private-photo" in {item.rule for item in findings}


def test_push_scan_rejects_secret_from_intermediate_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "guard@example.invalid")
    _git(tmp_path, "config", "user.name", "Guard Test")
    config = tmp_path / "settings.txt"
    config.write_text("password = change-me\n", encoding="utf-8")
    _git(tmp_path, "add", "settings.txt")
    _git(tmp_path, "commit", "--quiet", "-m", "safe base")
    base = _git_output(tmp_path, "rev-parse", "HEAD")

    unsafe_line = "{} = {}\n".format(
        "pass" + "word",
        "-".join(("correct", "horse", "battery", "staple")),
    )
    config.write_text(unsafe_line, encoding="utf-8")
    _git(tmp_path, "add", "settings.txt")
    _git(tmp_path, "commit", "--quiet", "-m", "accidental secret")
    secret_commit = _git_output(tmp_path, "rev-parse", "HEAD")
    config.write_text("password = change-me\n", encoding="utf-8")
    _git(tmp_path, "add", "settings.txt")
    _git(tmp_path, "commit", "--quiet", "-m", "clean working tree")
    head = _git_output(tmp_path, "rev-parse", "HEAD")

    assert not scan_repository(tmp_path)
    findings = scan_pushed_commits(tmp_path, from_ref=base, to_ref=head)

    assert "generic-secret" in {item.rule for item in findings}
    assert any(item.path.startswith(secret_commit[:12] + ":") for item in findings)


def test_initial_push_scan_checks_earlier_history(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "guard@example.invalid")
    _git(tmp_path, "config", "user.name", "Guard Test")
    photo = tmp_path / "portrait.jpg"
    photo.write_bytes(b"private image bytes")
    _git(tmp_path, "add", "portrait.jpg")
    _git(tmp_path, "commit", "--quiet", "-m", "accidental photo")
    photo.unlink()
    _git(tmp_path, "add", "-u")
    _git(tmp_path, "commit", "--quiet", "-m", "remove photo")

    findings = scan_pushed_commits(tmp_path)

    assert "private-photo" in {item.rule for item in findings}


def test_photoshop_document_is_treated_as_private_photo() -> None:
    assert "private-photo" in _rules("archive/portrait.psd", b"8BPS")
