"""Durable editor metadata, independent of exported photographs.

Small atomic JSON records are committed on the GUI thread. Full-size images are
only read/written by workers. Image identity includes the source fingerprint,
never a mutable queue row number. No data lives solely in a temporary directory.
"""

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

from colorpro.files import InputItem

HISTORY_LIMIT = 100


def identity(item):
    value = asdict(item)
    value["path"] = os.path.normcase(str(Path(item.path).resolve()))
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf8")).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf8")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.read_bytes() != raw:
            raise OSError("Не удалось проверить запись состояния редактора")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_json(path, limit=32 * 1024**2):
    path = Path(path)
    if not path.exists():
        return None
    if path.stat().st_size > limit:
        raise ValueError("Сохранённое состояние слишком велико")
    return json.loads(path.read_text(encoding="utf8"))


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs = self.root / "processed"
        self.jobs.mkdir(exist_ok=True)

    def edit_path(self, item):
        return self.root / "edits" / (identity(item) + ".json")

    def preserve_failed_queue(self):
        source = self.root / "queue.json"
        if source.exists():
            destination = self.root / ("queue-recovery-" + uuid.uuid4().hex + ".json")
            with source.open("rb") as src, destination.open("xb") as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            if source.read_bytes() != destination.read_bytes():
                raise OSError("Не удалось сохранить резервную копию сессии")

    def save_edit(self, item, base, current, history, future, view=None, base_sha=None):
        # Fail closed if the source was replaced while editing.
        item.unchanged()
        value = {
            "schema": 1,
            "identity": identity(item),
            "base": str(Path(base).resolve()),
            "base_sha256": base_sha,
            "current": current,
            "history": history[-HISTORY_LIMIT:],
            "future": future[-HISTORY_LIMIT:],
            "view": view or {},
        }
        atomic_json(self.edit_path(item), value)

    def load_edit(self, item, base, base_sha=None):
        value = read_json(self.edit_path(item), 1024**2)
        if value is None:
            return None
        if (
            value.get("schema") != 1
            or value.get("identity") != identity(item)
            or (
                not value.get("base_sha256")
                and value.get("base") != str(Path(base).resolve())
            )
        ):
            raise ValueError("Сохранённые правки относятся к другому изображению")
        if value.get("base_sha256"):
            # A repeat run can move an identical lossless base into a new job
            # folder. Its pixels/metadata, not that incidental path, bind edits.
            if base_sha is None:
                from colorpro.levels import digest

                base_sha = digest(base)
            if value["base_sha256"] != base_sha:
                raise ValueError("Базовое изображение изменено. Правки не применены.")
        # Validate all snapshots before any control or pixel worker receives them.
        from colorpro.levels import levels_lut
        from colorpro.manual_balance import validate_balance
        from colorpro.manual_hsl import validate_hsl
        from colorpro.manual_tone import validate_tone

        for name in ("history", "future"):
            if (
                not isinstance(value.get(name), list)
                or len(value[name]) > HISTORY_LIMIT
            ):
                raise ValueError("Повреждена история правок")
        for snapshot in [value["current"], *value["history"], *value["future"]]:
            if not isinstance(snapshot, (tuple, list)) or len(snapshot) != 4:
                raise ValueError("Повреждены параметры коррекции")
            levels_lut(snapshot[0])
            validate_tone(snapshot[1])
            validate_hsl(snapshot[2])
            validate_balance(snapshot[3])
        return value

    def remember_export(self, path, checksum):
        # Commit the intent before replacing the image, so a crash cannot cause
        # an exported file to be ingested as a source on the next folder import.
        path = str(Path(path).resolve())
        key = hashlib.sha256(os.path.normcase(path).encode("utf8")).hexdigest()
        atomic_json(
            self.root / "exports" / (key + ".json"), {"path": path, "sha256": checksum}
        )

    def export_paths(self, cancelled=lambda: False):
        paths = []
        for entry in (self.root / "exports").glob("*.json"):
            if cancelled():
                break
            value = read_json(entry, 65536)
            if value and Path(value["path"]).is_file():
                paths.append(value["path"])
        return paths

    def save_queue(self, items, results, selected=-1):
        atomic_json(
            self.root / "queue.json",
            {
                "schema": 1,
                "selected": selected,
                "rows": [
                    {"input": asdict(item), "record": results.get(i, {})}
                    for i, item in enumerate(items)
                ],
            },
        )

    def save_processed(self, item, record):
        atomic_json(
            self.root / "records" / (identity(item) + ".json"),
            {"identity": identity(item), "record": record},
        )

    def load_queue(self):
        value = read_json(self.root / "queue.json")
        if value is None:
            return [], {}, -1
        if value.get("schema") != 1 or not isinstance(value.get("rows"), list):
            raise ValueError("Не удалось прочитать сохранённую очередь")
        if len(value["rows"]) > 10000:
            raise ValueError("Повреждена сохранённая очередь")
        items, results = [], {}
        for index, row in enumerate(value["rows"]):
            item = InputItem(**row["input"])
            record = dict(row["record"], index=index)
            completed = read_json(self.root / "records" / (identity(item) + ".json"))
            if completed and not record.get("manually_edited"):
                if completed.get("identity") != identity(item):
                    raise ValueError("Результат относится к другому исходнику")
                record = dict(completed["record"], index=index)
            try:
                item.unchanged()
                base = record.get("base_output") or record.get("output")
                if base and not Path(base).is_file():
                    raise ValueError(
                        "Не найден сохранённый результат. Повторите обработку."
                    )
                if record.get("status") == "running":
                    record.update(status="cancelled", reason="Обработка была прервана")
            except (OSError, ValueError) as error:
                record.update(status="error", reason=str(error))
            items.append(item)
            results[index] = record
        selected = value.get("selected", -1)
        return items, results, selected if isinstance(selected, int) else -1
