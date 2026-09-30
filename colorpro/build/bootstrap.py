"""Isolated read-only dependency copies; never upgrade the training environment."""

import importlib.metadata as md
import os
import shutil
import sys
import venv
from pathlib import Path


def main():
    destination = Path(sys.argv[1]).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    venv.EnvBuilder(with_pip=True).create(destination)
    site = destination / "Lib/site-packages"
    names = [
        "torch",
        "numpy",
        "opencv-python-headless",
        "pillow",
        "sympy",
        "mpmath",
        "networkx",
        "filelock",
        "fsspec",
        "jinja2",
        "MarkupSafe",
        "typing_extensions",
        "PySide6-Essentials",
        "shiboken6",
    ]
    for name in names:
        dist = md.distribution(name)
        origin = Path(dist.locate_file("")).resolve()
        for entry in dist.files or []:
            src = Path(dist.locate_file(entry)).resolve()
            if not src.is_relative_to(origin) or not src.is_file() or "__pycache__" in src.parts:
                continue
            dst = site / src.relative_to(origin)
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
        print(f"{name}=={dist.version}", flush=True)


if __name__ == "__main__":
    main()
