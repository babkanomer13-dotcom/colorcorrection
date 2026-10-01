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
        compact_path = folder / (platform + "-compact.json")
        if compact_path.is_file():
            compact = json.loads(compact_path.read_text("utf8"))
            if compact.get("version") != __version__ or compact.get("platform") != platform:
                raise ValueError("Wrong compact build receipt")
            if len(files) != 1 or files[0]["size"] > 150 * 1024**2:
                raise ValueError("Unexpected files in compact release")
            manifest["kind"] = "compact"
        (folder / (f"ColorPro-{__version__}-{platform}-update.json")).write_text(
            json.dumps(manifest, indent=2), encoding="utf8"
        )
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.name.startswith("ColorPro-"))
    if any(p.stat().st_size >= 2 * 1024**3 for p in files):
        raise ValueError("GitHub asset limit exceeded (including offline installers)")
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
    release_files = files + [
        args.artifacts / "SHA256SUMS.txt",
        args.notes or args.artifacts / "release-notes.txt",
    ]
    if any(not path.is_file() for path in release_files):
        raise ValueError("Missing release notes or checksums")
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
        for path in release_files:
            print("Uploading", path.name, flush=True)
            gh("release", "upload", tag, str(path), "--repo", REPOSITORY)
    # Draft tags do not yet exist in Git and cannot be fetched via /tags/{tag}.
    release_url = gh(
        "release", "view", tag, "--repo", REPOSITORY, "--json", "apiUrl", "--jq", ".apiUrl"
    ).strip()
    if not re.fullmatch(
        r"https://api\.github\.com/repos/" + re.escape(REPOSITORY) + r"/releases/\d+", release_url
    ):
        raise ValueError("Unexpected draft URL")
    remote = json.loads(gh("api", release_url))
    if not remote["draft"]:
        raise ValueError("Refusing to modify an already published release")
    assets = {a["name"]: a for a in remote["assets"]}
    if set(assets) != {path.name for path in release_files}:
        raise ValueError("Unexpected or missing release assets")
    for path in release_files:
        a = assets[path.name]
        if a["size"] != path.stat().st_size or a.get("digest") != "sha256:" + sha256(path):
            raise ValueError("Remote asset digest mismatch: " + path.name)
    for platform in ("win10", "win7"):
        m = json.loads(
            (args.artifacts / (f"ColorPro-{__version__}-{platform}-update.json")).read_text("utf8")
        )
        # GitHub assigns drafts an untagged-* URL. No client sees a draft.
        # Check the future public URLs here, then check the real URLs after publish.
        planned = {
            name: dict(
                a,
                browser_download_url="https://github.com/"
                + REPOSITORY
                + "/releases/download/"
                + tag
                + "/"
                + name,
            )
            for name, a in assets.items()
        }
        validate_manifest(m, planned, __version__, platform)
    gh("release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--latest")
    published = json.loads(gh("api", "repos/" + REPOSITORY + "/releases/tags/" + tag))
    for platform in ("win10", "win7"):
        m = json.loads(
            (args.artifacts / f"ColorPro-{__version__}-{platform}-update.json").read_text("utf8")
        )
        validate_manifest(m, {a["name"]: a for a in published["assets"]}, __version__, platform)
    print("Published", published["html_url"])


if __name__ == "__main__":
    main()
