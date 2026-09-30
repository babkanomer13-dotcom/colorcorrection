"""Desktop and batch entrypoint; image processing has no network dependency."""

import argparse
import json
import os
import sys
from pathlib import Path


def initialize():
    from colorpro.config import load_config, verify_runtime

    config = load_config()
    verify_runtime(config)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "2"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, config["runtime_root"])
    return config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("PNG", "JPEG"), default="PNG")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--diagnose", type=Path)
    parser.add_argument("--qa-smoke", type=Path)
    parser.add_argument("--check-update", type=Path, help="Write read-only release check as JSON")
    args = parser.parse_args()
    config = initialize()
    from colorpro.updates import hold_application_mutex

    hold_application_mutex(config.get("platform"))
    if os.name == "nt":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ColorPro.Desktop.V39")
    if sys.stderr is None:
        logs = Path(config["state_root"]) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        sys.stderr = (logs / "application.log").open("a", encoding="utf8", buffering=1)
        sys.stdout = sys.stderr
    if args.check_update:
        from colorpro import __version__
        from colorpro.updates import latest_release

        result = dict(
            version=__version__,
            platform=config.get("platform", "win10"),
            update=latest_release(__version__, config.get("platform", "win10")),
        )
        args.check_update.parent.mkdir(parents=True, exist_ok=True)
        args.check_update.write_text(json.dumps(result, indent=2), encoding="utf8")
        return 0
    if args.diagnose or args.qa_smoke:
        from colorpro.diagnostics import diagnose

        result = diagnose(
            args.diagnose or args.qa_smoke, smoke=bool(args.qa_smoke), device=args.device
        )
        return 0 if result["status"] == "PASS" else 2
    if args.batch:
        if args.output is None:
            parser.error("--output required")
        from colorpro.batch import Control, run_batch
        from colorpro.files import collect_inputs

        items, errors = collect_inputs(args.batch)
        if errors:
            raise ValueError("; ".join(errors))

        def emit(event):
            if event["type"] != "preview":
                print(json.dumps(event, ensure_ascii=False), flush=True)

        report = run_batch(items, args.output, "v39", args.device, args.format, Control(), emit)
        return 0 if report["state"] == "completed" and not report["errors"] else 2
    from colorpro.ui import launch

    return launch(args.screenshot)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        import traceback

        traceback.print_exc()
        if "--batch" not in sys.argv and "--screenshot" not in sys.argv:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(None, "ColorPro", f"Не удалось запустить ColorPro.\n\n{error}")
        sys.exit(1)
