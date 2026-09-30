"""Collect legal texts from the exact build interpreter's installed distributions."""

import argparse
import importlib.metadata as md
import json
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    out = args.stage / "third-party-licenses"
    out.mkdir(exist_ok=True)
    records = {}
    for dist in md.distributions():
        name = dist.metadata.get("Name", "unknown")
        files = []
        for entry in dist.files or []:
            parts = str(entry).lower().replace("\\", "/").split("/")
            if not any("license" in p or p.startswith(("copying", "notice")) for p in parts):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file() or source.suffix.lower() in {".py", ".pyc", ".pyd", ".dll"}:
                continue
            if ".." in entry.parts or entry.is_absolute():
                continue
            target = out / name / str(entry)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            files.append(str(target.relative_to(out)))
        if files:
            records[name] = dict(version=dist.version, files=files)
    (out / "components.json").write_text(json.dumps(records, indent=2), encoding="utf8")
    print(
        json.dumps(
            dict(
                components=len(records),
                license_files=sum(len(x["files"]) for x in records.values()),
            )
        )
    )


if __name__ == "__main__":
    main()
