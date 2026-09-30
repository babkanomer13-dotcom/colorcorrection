"""One-photo-at-a-time batch processing with pause, cancellation and durable reports."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime

from colorpro import __version__
from colorpro.files import output_name, preview_bytes, read_image, save_result
from colorpro.safety import validate_output_parent


class Control:
    def __init__(self):
        self.stop = threading.Event()
        self.resume = threading.Event()
        self.resume.set()

    def cancel(self):
        self.stop.set()
        self.resume.set()

    def wait(self):
        while not self.resume.wait(0.1):
            if self.stop.is_set():
                return False
        return not self.stop.is_set()


def write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    tmp.replace(path)


def run_batch(items, parent, model, device, fmt, control, emit, engine_factory=None):
    if not items:
        raise ValueError("Сначала добавьте фотографии")
    if fmt not in {"PNG", "JPEG"}:
        raise ValueError("Неизвестный формат")
    if engine_factory is None:
        from colorpro.engine import Engine

        engine_factory = Engine
    parent = validate_output_parent(parent)
    parent.mkdir(parents=True, exist_ok=True)
    folder = parent / f"ColorPro_{datetime.now():%Y%m%d_%H%M%S}_{model}_{uuid.uuid4().hex[:6]}"
    folder.mkdir(exist_ok=False)
    report = dict(
        version=__version__,
        model=model,
        format=fmt,
        jpeg_quality=100 if fmt == "JPEG" else None,
        jpeg_subsampling="4:4:4" if fmt == "JPEG" else None,
        requested_device=device,
        total=len(items),
        state="initializing",
        records=[],
        output=str(folder),
        source_files_modified=False,
    )
    write_json(folder / "report.json", report)
    emit(dict(type="folder", path=str(folder)))
    engine = None
    started = time.monotonic()
    fatal = None
    try:
        if control.stop.is_set():
            return report
        engine = engine_factory(
            model, device, lambda message: emit(dict(type="stage", text=message))
        )
        report.update(
            device=engine.device_name,
            weights_sha256=engine.weight_sha256,
            recipe_sha256=engine.recipe_sha256,
            state="running",
        )
        emit(dict(type="ready", device=engine.device_name))
        for index, item in enumerate(items):
            paused = not control.resume.is_set()
            if paused:
                emit(dict(type="paused"))
            if not control.wait():
                break
            if paused:
                emit(dict(type="resumed"))
            emit(dict(type="start", index=index, text=item.label))
            step = time.monotonic()
            record = dict(index=index, input=asdict(item), name=item.label)
            try:
                source, metadata, source_sha = read_image(item)
                if metadata.get("container_note"):
                    record["container_note"] = metadata["container_note"]
                if metadata.get("raw_development"):
                    record["raw_development"] = metadata["raw_development"]
                pixels, stats = engine.process(source)
                if report["device"] != engine.device_name:
                    report["device"] = engine.device_name
                    emit(dict(type="ready", device=engine.device_name))
                result = folder / output_name(index + 1, item, fmt)
                save_result(result, pixels, metadata, fmt)
                record.update(
                    stats,
                    output=str(result),
                    source_sha256=source_sha,
                    seconds=round(time.monotonic() - step, 3),
                )
                # UI receives bounded previews; no full-batch decoded images remain in RAM.
                emit(
                    dict(
                        type="preview",
                        index=index,
                        before=preview_bytes(source),
                        after=preview_bytes(pixels),
                    )
                )
                del source, pixels
            except Exception as error:
                record.update(
                    status="error", reason=str(error), seconds=round(time.monotonic() - step, 3)
                )
                if (
                    isinstance(error, (MemoryError, OSError))
                    and (
                        isinstance(error, MemoryError) or getattr(error, "errno", None) in {28, 112}
                    )
                    or "out of memory" in str(error).lower()
                ):
                    fatal = "Недостаточно памяти или места на диске. Остаток очереди не обработан."
                    control.cancel()
            report["records"].append(record)
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            write_json(folder / "report.json", report)
            emit(
                dict(
                    type="result",
                    record=record,
                    done=index + 1,
                    total=len(items),
                    elapsed=report["elapsed_seconds"],
                )
            )
    except Exception as error:
        fatal = str(error)
        raise
    finally:
        try:
            if engine is not None:
                emit(dict(type="stage", text="Освобождение ресурсов и сохранение отчёта…"))
                engine.close()
        except Exception as error:
            fatal = f"Ошибка завершения обработчика: {error}"
        report.update(
            state="failed" if fatal else "cancelled" if control.stop.is_set() else "completed",
            error=fatal,
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
        report["processed"] = len(report["records"])
        report["remaining"] = len(items) - report["processed"]
        report["corrected"] = sum(r["status"] == "corrected" for r in report["records"])
        report["attention"] = sum(
            r["status"] in {"partial", "needs_attention"} for r in report["records"]
        )
        report["errors"] = sum(r["status"] == "error" for r in report["records"])
        write_json(folder / "report.json", report)
        emit(dict(type="finished", report=report))
    return report
