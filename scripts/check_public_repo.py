#!/usr/bin/env python3
"""Reject private or unsafe artifacts before they reach the public repository.

With no path arguments the guard scans all tracked working-tree files.  The
``--staged`` mode reads blobs from the Git index, rather than from the working
tree, and is therefore suitable for pre-commit.  ``--pushed`` scans the exact
blob at every changed path in every commit being pushed, so replacing a secret
in the working tree cannot hide it from the pre-push hook.  Explicit paths are
useful for checking newly created files before they are staged.

The script intentionally uses only the Python standard library so the privacy
check can run before the project's optional dependencies are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_BINARY_BYTES = 1024 * 1024
MAX_SYNTHETIC_IMAGE_BYTES = 1024 * 1024
MAX_SYNTHETIC_IMAGE_SIDE = 512
MAX_SYNTHETIC_IMAGE_PIXELS = 512 * 512
GIT_EXECUTABLE = shutil.which("git")
# Reviewed public branding only, pinned by content as well as exact path.
# No photographs, arbitrary replacements or other files in assets are exempted.
PUBLIC_BRANDING = {
    "colorpro/assets/logo.png": "2e41d2cdf5ddb0f5550c718a115554171936326fbad263ca11c40bded602bb3c",
}
_GIT_OBJECT_ID_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")

PHOTO_EXTENSIONS = {
    ".3fr",
    ".arw",
    ".avif",
    ".bmp",
    ".cr2",
    ".cr3",
    ".dng",
    ".gif",
    ".heic",
    ".heif",
    ".iiq",
    ".jpe",
    ".jpeg",
    ".jpg",
    ".nef",
    ".nrw",
    ".orf",
    ".pef",
    ".png",
    ".psb",
    ".psd",
    ".raf",
    ".raw",
    ".rw2",
    ".sr2",
    ".srf",
    ".tif",
    ".tiff",
    ".webp",
    ".x3f",
}
SYNTHETIC_IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}
WEIGHT_EXTENSIONS = {
    ".bin",
    ".ckpt",
    ".h5",
    ".hdf5",
    ".joblib",
    ".onnx",
    ".pb",
    ".pickle",
    ".pkl",
    ".pt",
    ".pth",
    ".safetensors",
    ".tflite",
}
PRIVATE_BINARY_EXTENSIONS = {
    ".7z",
    ".arrow",
    ".avi",
    ".bz2",
    ".db",
    ".doc",
    ".docx",
    ".flac",
    ".gz",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".npy",
    ".npz",
    ".parquet",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rar",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tgz",
    ".wav",
    ".xls",
    ".xlsx",
    ".xz",
    ".zip",
}
SYNTHETIC_BINARY_EXTENSIONS = {
    ".arrow",
    ".db",
    ".npy",
    ".npz",
    ".parquet",
    ".sqlite",
    ".sqlite3",
}
SENSITIVE_FILENAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "secrets.json",
}
SENSITIVE_SUFFIXES = {".jks", ".key", ".p12", ".pem", ".pfx"}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("github-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b")),
    ("stripe-secret", re.compile(r"\b[rs]k_(?:live|test)_[0-9A-Za-z]{20,}\b")),
    (
        "credential-in-url",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]{6,}@", re.IGNORECASE),
    ),
)
GENERIC_SECRET_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|client[_-]?secret|secret(?:[_-]?key)?|"
    r"access[_-]?token|auth[_-]?token|password|passwd)\b"
    r"\s*[:=]\s*[\"']?([^\s\"'#;,]{8,})"
)
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/](?:[^\s\"'<>|]+[\\/]?)*)")
WINDOWS_UNC_PATH_RE = re.compile(r"(?<![\\])\\\\[^\s\\/]+[\\/][^\s\\/]+")
POSIX_PRIVATE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])/(?:home|Users)/[A-Za-z0-9._-]+(?:/[^\s\"'<>]*)?"
)
WSL_PRIVATE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])/mnt/[a-zA-Z]/Users/[A-Za-z0-9._-]+(?:/[^\s\"'<>]*)?"
)


@dataclass(frozen=True)
class Finding:
    """One public-repository policy violation."""

    path: str
    rule: str
    message: str
    line: int | None = None

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line is not None else self.path
        return f"ERROR [{self.rule}] {location}: {self.message}"


class GitError(RuntimeError):
    """Raised when repository state cannot be read safely."""


def _normalise_repo_path(path: str | Path) -> str:
    normalised = PurePosixPath(str(path).replace("\\", "/")).as_posix()
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def is_synthetic_fixture(path: str | Path) -> bool:
    """Return whether *path* is inside the sole public binary-fixture area."""

    normalised = _normalise_repo_path(path)
    parts = PurePosixPath(normalised).parts
    return len(parts) >= 4 and parts[:3] == ("tests", "fixtures", "synthetic")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip("\"'[](){}<>").lower()
    markers = (
        "change-me",
        "changeme",
        "dummy",
        "example",
        "fake",
        "placeholder",
        "redacted",
        "removed",
        "sample",
        "test-only",
        "your-",
        "your_",
    )
    return (
        not lowered
        or lowered in {"none", "null", "secret_here", "token_here"}
        or set(lowered) <= {"x", "*", "-", "_"}
        or any(marker in lowered for marker in markers)
        or value.startswith(("${", "{{", "<"))
        or lowered.startswith(("getenv(", "os.environ", "os.getenv("))
    )


def _is_probably_binary(data: bytes) -> bool:
    sample = data[:8192]
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    controls = sum(byte < 32 and byte not in b"\t\n\r\f\b" for byte in sample)
    return controls / len(sample) > 0.10


def _detected_photo_format(data: bytes) -> str | None:
    """Identify common image containers even when their extension was changed."""

    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff/raw"
    if data.startswith(b"8BPS"):
        return "photoshop"
    if data.startswith(b"BM") and len(data) >= 14:
        return "bmp"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brands = data[8:32]
        if any(brand in brands for brand in (b"avif", b"heic", b"heif", b"mif1")):
            return "heif/avif"
    return None


def _png_info(data: bytes) -> tuple[int, int, bool] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height, b"eXIf" in data


def _bmp_info(data: bytes) -> tuple[int, int, bool] | None:
    if len(data) < 26 or data[:2] != b"BM":
        return None
    width, height = struct.unpack("<ii", data[18:26])
    return abs(width), abs(height), False


def _jpeg_info(data: bytes) -> tuple[int, int, bool] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    offset = 2
    has_exif = False
    start_of_frame = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            break
        payload = data[offset + 2 : offset + segment_length]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            has_exif = True
        if marker in start_of_frame and len(payload) >= 5:
            height = int.from_bytes(payload[1:3], "big")
            width = int.from_bytes(payload[3:5], "big")
            return width, height, has_exif
        offset += segment_length
    return None


def _webp_info(data: bytes) -> tuple[int, int, bool] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height, b"EXIF" in data
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height, b"EXIF" in data
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height, b"EXIF" in data
    return None


def _synthetic_image_info(suffix: str, data: bytes) -> tuple[int, int, bool] | None:
    if suffix == ".png":
        return _png_info(data)
    if suffix == ".bmp":
        return _bmp_info(data)
    if suffix in {".jpg", ".jpeg"}:
        return _jpeg_info(data)
    if suffix == ".webp":
        return _webp_info(data)
    return None


def _scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for rule, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(
                Finding(
                    path,
                    rule,
                    "possible secret material; remove it and rotate the credential if it is real",
                    _line_number(text, match.start()),
                )
            )

    for match in GENERIC_SECRET_RE.finditer(text):
        if not _looks_like_placeholder(match.group(1)):
            findings.append(
                Finding(
                    path,
                    "generic-secret",
                    "a credential-like assignment contains a non-placeholder value",
                    _line_number(text, match.start()),
                )
            )

    for pattern in (
        WINDOWS_ABSOLUTE_PATH_RE,
        WINDOWS_UNC_PATH_RE,
        POSIX_PRIVATE_PATH_RE,
        WSL_PRIVATE_PATH_RE,
    ):
        for match in pattern.finditer(text):
            findings.append(
                Finding(
                    path,
                    "absolute-private-path",
                    "replace the machine-specific absolute path with configuration "
                    "or a placeholder",
                    _line_number(text, match.start()),
                )
            )
    return findings


def inspect_file(
    path: str | Path,
    data: bytes,
    *,
    declared_size: int | None = None,
) -> list[Finding]:
    """Inspect one repository-relative file and return all policy violations."""

    normalised = _normalise_repo_path(path)
    suffix = PurePosixPath(normalised).suffix.lower()
    basename = PurePosixPath(normalised).name.lower()
    size = len(data) if declared_size is None else declared_size
    synthetic = is_synthetic_fixture(normalised)
    branding = PUBLIC_BRANDING.get(normalised) == hashlib.sha256(data).hexdigest()
    detected_photo_format = _detected_photo_format(data)
    findings: list[Finding] = []

    env_file = basename == ".env" or (
        basename.startswith(".env.") and basename not in {".env.example", ".env.template"}
    )
    if env_file or basename in SENSITIVE_FILENAMES or suffix in SENSITIVE_SUFFIXES:
        findings.append(
            Finding(normalised, "sensitive-file", "secret-bearing file type must not be tracked")
        )

    if suffix in WEIGHT_EXTENSIONS:
        findings.append(
            Finding(
                normalised,
                "model-weight",
                "model weights and serialized objects must stay local",
            )
        )

    if (suffix in PHOTO_EXTENSIONS or detected_photo_format is not None) and not (
        synthetic or branding
    ):
        findings.append(
            Finding(
                normalised,
                "private-photo",
                "photos are allowed only as verified fixtures under tests/fixtures/synthetic",
            )
        )

    if synthetic and detected_photo_format is not None and suffix not in SYNTHETIC_IMAGE_EXTENSIONS:
        findings.append(
            Finding(
                normalised,
                "unsafe-synthetic-image",
                f"{detected_photo_format} image content uses a non-image fixture extension",
            )
        )

    if suffix in PRIVATE_BINARY_EXTENSIONS and not (
        synthetic and suffix in SYNTHETIC_BINARY_EXTENSIONS
    ):
        findings.append(
            Finding(normalised, "private-artifact", "binary data/artifact must remain outside Git")
        )

    if size > MAX_FILE_BYTES:
        findings.append(
            Finding(normalised, "large-file", f"file is {size} bytes (limit: {MAX_FILE_BYTES})")
        )

    probably_binary = _is_probably_binary(data)
    if probably_binary and size > MAX_BINARY_BYTES:
        findings.append(
            Finding(
                normalised,
                "large-binary",
                f"binary file is {size} bytes (limit: {MAX_BINARY_BYTES})",
            )
        )

    if synthetic and suffix in PHOTO_EXTENSIONS:
        if suffix not in SYNTHETIC_IMAGE_EXTENSIONS:
            findings.append(
                Finding(
                    normalised,
                    "unsafe-synthetic-image",
                    "use PNG, JPEG, BMP, or WebP for synthetic image fixtures",
                )
            )
        elif size > MAX_SYNTHETIC_IMAGE_BYTES:
            findings.append(
                Finding(
                    normalised,
                    "unsafe-synthetic-image",
                    f"synthetic image exceeds {MAX_SYNTHETIC_IMAGE_BYTES} bytes",
                )
            )
        else:
            info = _synthetic_image_info(suffix, data)
            if info is None:
                findings.append(
                    Finding(
                        normalised,
                        "unsafe-synthetic-image",
                        "image signature or dimensions could not be validated",
                    )
                )
            else:
                width, height, has_exif = info
                if width <= 0 or height <= 0:
                    findings.append(
                        Finding(
                            normalised,
                            "unsafe-synthetic-image",
                            "image dimensions are invalid",
                        )
                    )
                if (
                    width > MAX_SYNTHETIC_IMAGE_SIDE
                    or height > MAX_SYNTHETIC_IMAGE_SIDE
                    or width * height > MAX_SYNTHETIC_IMAGE_PIXELS
                ):
                    findings.append(
                        Finding(
                            normalised,
                            "unsafe-synthetic-image",
                            f"synthetic image is {width}x{height}; maximum is 512x512",
                        )
                    )
                if has_exif:
                    findings.append(
                        Finding(
                            normalised,
                            "unsafe-synthetic-image",
                            "synthetic fixtures must not contain EXIF metadata",
                        )
                    )

    if data and not probably_binary:
        text = data.decode("utf-8", errors="replace")
        findings.extend(_scan_text(normalised, text))

    # A file can match overlapping path/size rules; exact duplicates add no value.
    return list(dict.fromkeys(findings))


def _run_git(repo: Path, arguments: Sequence[str]) -> bytes:
    if GIT_EXECUTABLE is None:
        raise GitError("git executable was not found on PATH")
    process = subprocess.run(  # noqa: S603 - argv is passed without a shell
        [GIT_EXECUTABLE, "-c", "core.quotepath=false", *arguments],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(detail or f"git {' '.join(arguments)} failed")
    return process.stdout


def _git_paths(repo: Path, *, staged_only: bool) -> list[str]:
    arguments = (
        ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--"]
        if staged_only
        else ["ls-files", "-z"]
    )
    raw = _run_git(repo, arguments)
    return [item.decode("utf-8", errors="surrogateescape") for item in raw.split(b"\0") if item]


def _to_repo_relative(repo: Path, path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = repo / candidate
    try:
        return candidate.resolve(strict=False).relative_to(repo.resolve()).as_posix()
    except ValueError as error:
        raise GitError(f"path is outside the repository: {path}") from error


def _working_tree_content(repo: Path, path: str) -> tuple[bytes, int]:
    target = repo / PurePosixPath(path)
    if target.is_symlink():
        link_target = target.readlink().as_posix().encode("utf-8")
        return link_target, len(link_target)
    try:
        size = target.stat().st_size
    except OSError as error:
        raise GitError(f"cannot stat {path}: {error}") from error
    if size > MAX_FILE_BYTES:
        return b"", size
    try:
        return target.read_bytes(), size
    except OSError as error:
        raise GitError(f"cannot read {path}: {error}") from error


def _staged_content(repo: Path, path: str) -> tuple[bytes, int]:
    object_name = f":{path}"
    raw_size = _run_git(repo, ["cat-file", "-s", object_name])
    try:
        size = int(raw_size.strip())
    except ValueError as error:
        raise GitError(f"Git returned an invalid size for staged file {path}") from error
    if size > MAX_FILE_BYTES:
        return b"", size
    return _run_git(repo, ["cat-file", "blob", object_name]), size


def _validated_object_id(value: str, *, label: str) -> str:
    candidate = value.strip()
    if not _GIT_OBJECT_ID_RE.fullmatch(candidate):
        raise GitError(f"{label} is not a full Git object id")
    return candidate


def _push_commits(repo: Path, from_ref: str | None, to_ref: str | None) -> list[str]:
    """Return every commit whose path changes are about to be introduced."""

    if (from_ref is None) != (to_ref is None):
        raise GitError("push scan requires both from-ref and to-ref")
    if from_ref is not None and to_ref is not None:
        source = _validated_object_id(from_ref, label="from-ref")
        target = _validated_object_id(to_ref, label="to-ref")
        raw = _run_git(
            repo,
            ["rev-list", "--reverse", "--topo-order", f"{source}..{target}"],
        )
    else:
        # pre-commit's initial-push/all-files path does not expose a range to
        # child hooks. Auditing all reachable HEAD history is conservative and
        # catches an earlier secret even when a later commit replaced it.
        raw = _run_git(repo, ["rev-list", "--reverse", "--topo-order", "HEAD"])
    commits = [line.decode("ascii") for line in raw.splitlines() if line]
    for commit in commits:
        _validated_object_id(commit, label="rev-list result")
    return commits


def _changed_paths_in_commit(repo: Path, commit: str) -> list[str]:
    raw = _run_git(
        repo,
        [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "--diff-filter=ACMR",
            "-r",
            "-m",
            "-z",
            commit,
        ],
    )
    return [item.decode("utf-8", errors="surrogateescape") for item in raw.split(b"\0") if item]


def _blob_at_commit(repo: Path, commit: str, path: str) -> tuple[str, bytes, int] | None:
    tree = _run_git(repo, ["ls-tree", "-z", "--full-tree", commit, "--", path])
    entries = [entry for entry in tree.split(b"\0") if entry]
    if not entries:
        return None
    if len(entries) != 1 or b"\t" not in entries[0]:
        raise GitError(f"unexpected ls-tree result for {commit[:12]}:{path}")
    header, returned_path = entries[0].split(b"\t", 1)
    if returned_path.decode("utf-8", errors="surrogateescape") != path:
        raise GitError(f"ls-tree returned the wrong path for {commit[:12]}:{path}")
    fields = header.split()
    if len(fields) != 3:
        raise GitError(f"unexpected ls-tree header for {commit[:12]}:{path}")
    _mode, object_type, raw_object_id = fields
    if object_type != b"blob":
        return None
    object_id = _validated_object_id(raw_object_id.decode("ascii"), label="blob id")
    raw_size = _run_git(repo, ["cat-file", "-s", object_id])
    try:
        size = int(raw_size.strip())
    except ValueError as error:
        raise GitError(f"Git returned an invalid size for blob {object_id}") from error
    data = b"" if size > MAX_FILE_BYTES else _run_git(repo, ["cat-file", "blob", object_id])
    return object_id, data, size


def scan_pushed_commits(
    repo: str | Path,
    *,
    from_ref: str | None = None,
    to_ref: str | None = None,
) -> list[Finding]:
    """Inspect historical blobs introduced by a pre-push revision range."""

    root = Path(repo).resolve()
    findings: list[Finding] = []
    blob_cache: dict[str, tuple[bytes, int]] = {}
    inspected_states: set[tuple[str, str]] = set()
    for commit in _push_commits(root, from_ref, to_ref):
        for path in sorted(set(_changed_paths_in_commit(root, commit))):
            blob = _blob_at_commit(root, commit, path)
            if blob is None:
                continue
            object_id, data, size = blob
            state = (object_id, path)
            if state in inspected_states:
                continue
            inspected_states.add(state)
            if object_id in blob_cache:
                data, size = blob_cache[object_id]
            else:
                blob_cache[object_id] = (data, size)
            for finding in inspect_file(path, data, declared_size=size):
                findings.append(
                    Finding(
                        path=f"{commit[:12]}:{finding.path}",
                        rule=finding.rule,
                        message=finding.message,
                        line=finding.line,
                    )
                )
    return findings


def scan_repository(
    repo: str | Path,
    *,
    staged_only: bool = False,
    paths: Iterable[str] | None = None,
) -> list[Finding]:
    """Scan tracked, staged, or explicitly named files in *repo*."""

    root = Path(repo).resolve()
    requested = list(paths or ())
    candidates = (
        [_to_repo_relative(root, item) for item in requested]
        if requested
        else _git_paths(root, staged_only=staged_only)
    )
    findings: list[Finding] = []
    for path in sorted(set(candidates)):
        try:
            data, size = (
                _staged_content(root, path) if staged_only else _working_tree_content(root, path)
            )
        except GitError as error:
            findings.append(Finding(path, "unreadable-file", str(error)))
            continue
        findings.extend(inspect_file(path, data, declared_size=size))
    return findings


def _repository_root(value: str | None) -> Path:
    if value is not None:
        root = Path(value).resolve()
    else:
        if GIT_EXECUTABLE is None:
            raise GitError("git executable was not found on PATH")
        process = subprocess.run(  # noqa: S603 - constant argv, no shell
            [GIT_EXECUTABLE, "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            raise GitError("not inside a Git repository; pass --repo explicitly")
        root = Path(process.stdout.decode("utf-8", errors="replace").strip()).resolve()
    if not (root / ".git").exists():
        raise GitError(f"not a Git repository: {root}")
    return root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="specific working-tree paths to inspect")
    parser.add_argument("--repo", help="repository root (defaults to the current Git repository)")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="scan staged blobs from the Git index (used by pre-commit)",
    )
    parser.add_argument(
        "--pushed",
        action="store_true",
        help="scan every changed blob in commits being pushed (used by pre-push)",
    )
    parser.add_argument("--from-ref", help=argparse.SUPPRESS)
    parser.add_argument("--to-ref", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = _repository_root(args.repo)
        if args.staged and args.pushed:
            raise GitError("--staged and --pushed are mutually exclusive")
        if args.pushed and args.paths:
            raise GitError("--pushed does not accept working-tree paths")
        if args.pushed:
            findings = scan_pushed_commits(
                root,
                from_ref=args.from_ref or os.environ.get("PRE_COMMIT_FROM_REF"),
                to_ref=args.to_ref or os.environ.get("PRE_COMMIT_TO_REF"),
            )
        else:
            findings = scan_repository(
                root,
                staged_only=args.staged,
                paths=args.paths if args.paths else None,
            )
    except GitError as error:
        print(f"ERROR [guard] {error}", file=sys.stderr)
        return 2

    if findings:
        for finding in findings:
            print(finding.render())
        print(f"Public repository guard failed with {len(findings)} finding(s).")
        return 1

    if args.pushed:
        scope = "all changed blobs in pushed commits"
    else:
        scope = "staged files" if args.staged and not args.paths else "requested/tracked files"
    print(f"Public repository guard passed ({scope}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
