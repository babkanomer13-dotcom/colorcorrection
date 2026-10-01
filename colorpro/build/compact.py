"""Build file-level update payloads against immutable, released runtime baselines.

All supported bases are compared. A file is omitted ONLY if identical in every
base. The installer verifies omitted files before any replacement. No model or
runtime DLL is silently bundled into a routine code update.
"""

import argparse
import json
import re
from pathlib import Path

from colorpro import __version__
from colorpro.updates import sha256, validate_manifest


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink in distribution")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if "payload/python/" in name and "/__pycache__/" in name:
                continue  # Disposable caches from QA/imports, never release payload.
            if not re.fullmatch(r"[A-Za-z0-9_./+()@ -]+", name):
                raise ValueError("Unexpected distribution file: " + name)
            result[name] = dict(sha256=sha256(path), size=path.stat().st_size)
    if "ColorPro.exe" not in result:
        raise ValueError("Missing application")
    return result


def plan(current, bases):
    if not bases:
        raise ValueError("At least one released baseline is required")
    # A removed runtime file requires an explicit full/runtime migration release.
    if any(set(base) - set(current) for base in bases):
        raise ValueError("Removed distribution files require a runtime migration")
    changed = {
        name: row for name, row in current.items() if any(base.get(name) != row for base in bases)
    }
    for name in changed:
        if name.endswith((".dll", ".pyd", ".pt", ".onnx", ".npy")):
            raise ValueError("Runtime/model changed: full baseline required: " + name)
    if sum(row["size"] for row in changed.values()) > 150 * 1024**2:
        raise ValueError("Not a compact application update")
    return changed, {n: r for n, r in current.items() if n not in changed}


def generate(dist, bases, output, platform, baseline_manifest, release_metadata):
    current = inventory(dist)
    changed, required = plan(current, [inventory(p) for p in bases])
    baseline = json.loads(baseline_manifest.read_text("utf8"))
    remote = json.loads(release_metadata.read_text("utf8"))
    if remote.get("draft") or remote.get("tag_name") != "colorpro-v" + baseline["version"]:
        raise ValueError("Runtime baseline must already be published")
    verified = validate_manifest(
        baseline, {a["name"]: a for a in remote["assets"]}, baseline["version"], platform
    )
    output.mkdir(parents=True, exist_ok=False)
    # Static, validated source paths; no downloaded manifest can choose destinations.
    lines = []
    for name, row in changed.items():
        relative = name.replace("/", "\\")
        parent = str(Path(relative).parent)
        dest = "{app}" + ("\\" + parent if parent != "." else "")
        lines.append(
            (
                'Source: "{}"; DestDir: "{}"; Flags: ignoreversion; '
                "Check: NeedsFile('{}', '{}')"
            ).format(dist / relative, dest, relative, row["sha256"])
        )
    (output / "files.iss").write_text("\n".join(lines) + "\n", encoding="utf8")
    (output / "required.txt").write_text(
        "\n".join(r["sha256"] + "|" + n.replace("/", "\\") for n, r in required.items()),
        encoding="utf8",
    )
    (output / "targets.txt").write_text(
        "\n".join(n.replace("/", "\\") for n in current), encoding="utf8"
    )
    code = ["procedure AddBaselineFiles;", "begin"]
    for row in verified["files"]:
        code.append(
            "  AddComponent('{}', '{}', '{}');".format(row["name"], row["sha256"], row["url"])
        )
    code += [
        "end;",
        "",
        "function BaselineInstaller: String;",
        "begin",
        "  Result := '{}';".format(verified["installer"]),
        "end;",
    ]
    (output / "baseline.iss").write_text("\n".join(code), encoding="utf8")
    report = dict(
        schema="colorpro-compact-v1",
        version=__version__,
        platform=platform,
        baseline_version=baseline["version"],
        changed=changed,
        required=required,
        download_bytes=sum(r["size"] for r in verified["files"]),
        changed_bytes=sum(r["size"] for r in changed.values()),
        preserved_bytes=sum(r["size"] for r in required.values()),
    )
    (output / "compact.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--base", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=("win10", "win7"), required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--release-metadata", type=Path, required=True)
    args = parser.parse_args()
    result = generate(
        args.dist.resolve(),
        [p.resolve() for p in args.base],
        args.output,
        args.platform,
        args.baseline_manifest,
        args.release_metadata,
    )
    print(json.dumps({k: v for k, v in result.items() if k not in ("changed", "required")}))


if __name__ == "__main__":
    main()
