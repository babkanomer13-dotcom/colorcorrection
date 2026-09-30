"""Prepare and publish complete, hash-checked releases; no tokens or photos in assets.

Publication starts as a draft. Both OS manifests and every remote GitHub digest
must match local files before that draft can be made visible to the updater.
"""

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from colorpro import __version__
from colorpro.updates import REPOSITORY, sha256, validate_manifest


def gh(*args):
    executable = shutil.which("gh")
    if not executable:
        raise RuntimeError("GitHub CLI required only on the publishing workstation")
    result = subprocess.run(  # noqa: S603 -- developer CLI, explicit argument array
        [executable, *args], text=True, encoding="utf8", capture_output=True, check=True
    )
    return result.stdout


def prepare(folder):
    for platform in ("win10", "win7"):
        prefix = "ColorPro-{}-{}-x64-Setup".format(__version__, platform.replace("win", "Win"))
        paths = sorted(
            p
            for p in folder.glob(prefix + "*")
            if re.fullmatch(re.escape(prefix) + r"(?:\.exe|-\d+[a-z]?\.bin)", p.name)
        )
        if not (folder / (prefix + ".exe")).is_file():
            raise ValueError("Missing installer for " + platform)
        files = [dict(name=p.name, size=p.stat().st_size, sha256=sha256(p)) for p in paths]
        if any(f["size"] >= 2 * 1024**3 for f in files):
            raise ValueError("GitHub asset limit exceeded")
        manifest = dict(
            schema="colorpro-update-v1",
            version=__version__,
            platform=platform,
            installer=prefix + ".exe",
            files=files,
        )
        (folder / (f"ColorPro-{__version__}-{platform}-update.json")).write_text(
            json.dumps(manifest, indent=2), encoding="utf8"
        )
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.name.startswith("ColorPro-"))
    (folder / "SHA256SUMS.txt").write_text(
        "".join(sha256(p) + "  " + p.name + "\n" for p in files), encoding="ascii"
    )
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--commit", help="Explicit tested source commit; never implicit dirty HEAD")
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--verify-draft", action="store_true")
    args = parser.parse_args()
    files = prepare(args.artifacts)
    tag = "colorpro-v" + __version__
    if not args.publish and not args.verify_draft:
        print("Prepared", tag, len(files), "assets")
        return
    if args.publish:
        if not args.commit or not re.fullmatch(r"[0-9a-f]{40}", args.commit) or not args.notes:
            parser.error("--publish requires explicit --commit and --notes")
        gh(
            "release",
            "create",
            tag,
            "--repo",
            REPOSITORY,
            "--target",
            args.commit,
            "--draft",
            "--title",
            "ColorPro " + __version__,
            "--notes-file",
            str(args.notes),
        )
        # Sequential uploads are retryable with gh release upload (no --clobber).
        for path in files + [args.artifacts / "SHA256SUMS.txt", args.notes]:
            print("Uploading", path.name, flush=True)
            gh("release", "upload", tag, str(path), "--repo", REPOSITORY)
    remote = json.loads(gh("api", "repos/" + REPOSITORY + "/releases/tags/" + tag))
    if not remote["draft"]:
        raise ValueError("Refusing to modify an already published release")
    assets = {a["name"]: a for a in remote["assets"]}
    for path in files:
        a = assets[path.name]
        if a["size"] != path.stat().st_size or a.get("digest") != "sha256:" + sha256(path):
            raise ValueError("Remote asset digest mismatch: " + path.name)
    for platform in ("win10", "win7"):
        m = json.loads(
            (args.artifacts / (f"ColorPro-{__version__}-{platform}-update.json")).read_text("utf8")
        )
        validate_manifest(m, assets, __version__, platform)
    gh("release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--latest")
    print("Published", remote["html_url"])


if __name__ == "__main__":
    main()
