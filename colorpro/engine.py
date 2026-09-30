"""Pinned V39 raw epoch 5. No fine tuning, residual adapter or target access."""

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

from colorpro.config import load_config, verify_runtime


def inventory():
    executable = shutil.which("nvidia-smi")
    if not executable:
        raise RuntimeError("NVIDIA driver utility not found")
    proc = subprocess.run(  # noqa: S603 -- resolved driver utility, fixed arguments, no shell
        [
            executable,
            "--query-gpu=uuid,name,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if proc.returncode:
        raise RuntimeError("Не удалось прочитать состояние NVIDIA")
    return [row for row in csv.reader(io.StringIO(proc.stdout), skipinitialspace=True) if row]


def device_candidates(torch, preference):
    """Use CUDA's own indices; never pin this product to a developer's card UUID."""
    if preference not in {"auto", "cuda", "cpu"}:
        raise ValueError("Неизвестный режим обработки")
    if preference == "cpu":
        return [("cpu", "Процессор · CPU")]
    try:
        rows = inventory()  # Optional load hint; CUDA/CPU do not require nvidia-smi.
    except (OSError, RuntimeError, subprocess.SubprocessError):
        rows = []

    def normalized_uuid(value):
        value = str(value).lower()
        return (value[4:] if value.startswith("gpu-") else value).replace("-", "")

    loads = {}
    for row in rows:
        try:
            loads[normalized_uuid(row[0])] = int(row[3])
        except (ValueError, IndexError):
            continue
    candidates = []
    try:
        count = torch.cuda.device_count() if torch.cuda.is_available() else 0
    except RuntimeError:
        count = 0
    for index in range(count):
        try:
            props = torch.cuda.get_device_properties(index)
            if loads.get(normalized_uuid(getattr(props, "uuid", "")), 0) >= 90:
                continue
            free, _ = torch.cuda.mem_get_info(index)
            if free >= 512 * 1024**2:
                candidates.append((free, index, props.name))
        except RuntimeError:
            continue
    choices = [(f"cuda:{i}", name) for _, i, name in sorted(candidates, reverse=True)]
    if preference == "auto":
        choices.append(("cpu", "Процессор · CPU"))
    if not choices:
        raise RuntimeError(
            "Доступная NVIDIA CUDA не найдена или занята. Выберите «Автоматически» или CPU."
        )
    return choices


def warmup(torch, model, device):
    """Check actual model kernels, not just whether a driver lists a GPU."""
    with torch.inference_mode():
        model.decide(
            torch.zeros((1, 3, 128, 128), device=device),
            torch.zeros((1, model.feature_count), device=device),
        )
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)


class BatchLease:
    """Kernel-released lock: a crash cannot leave a permanently busy app."""

    def __init__(self, path):
        import msvcrt

        self.file = None
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("a+b")
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            stream.close()
            raise RuntimeError("Другая пачка ColorPro уже обрабатывается") from exc
        self.file = stream

    def close(self):
        if self.file is not None:
            import msvcrt

            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
            self.file = None


class Engine:
    def __init__(self, model, device, emit=lambda text: None):
        if model != "v39" or device not in {"auto", "cuda", "cpu"}:
            raise ValueError("Неверная модель или режим обработки")
        self.model = self.detector = self.lease = None
        self.preference, self.emit = device, emit
        config = load_config()
        self.config = config
        emit("Проверка сохранённой V39 и выбор устройства обработки…")
        verify_runtime(config)
        self.lease = BatchLease(Path(config["state_root"]) / "processing.lock")
        try:
            import cv2
            import torch

            from colorcorrection.classic_face_inference import load_face_controller
            from colorcorrection.source_face_detector import SourceFaceDetector

            torch.set_num_threads(2)
            cv2.setNumThreads(2)
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            torch.backends.cudnn.benchmark = False
            torch.use_deterministic_algorithms(True)
            emit("Загрузка V39 · автоинструменты и уровни…")
            # Validate/deserialise on CPU outside the GPU fallback path. Corrupt
            # weights must fail, not be silently treated as a CUDA problem.
            self.model = load_face_controller(
                Path(config["checkpoint"]),
                config["checkpoint_sha256"],
                scope="raw",
                device="cpu",
            )
            errors = []
            for selected, name in device_candidates(torch, device):
                try:
                    self.model.to(selected)
                    warmup(torch, self.model, selected)
                except RuntimeError as exc:
                    if selected == "cpu":
                        raise
                    errors.append(str(exc))
                    emit(f"{name} недоступна для V39; проверяю следующий вариант…")
                    # Reload rather than trust a partially moved CUDA module.
                    self.model = load_face_controller(
                        Path(config["checkpoint"]), config["checkpoint_sha256"], device="cpu"
                    )
                    continue
                self.device = selected
                self.device_name = f"{name} · V39"
                emit(f"Устройство: {self.device_name}")
                break
            else:
                raise RuntimeError(
                    "Не удалось запустить V39 на GPU. Выберите CPU. " + "; ".join(errors)
                )
            self.detector = SourceFaceDetector(Path(config["detector"]))
            self.weight_sha256 = config["checkpoint_sha256"]
            self.recipe_sha256 = hashlib.sha256(
                json.dumps(config["bindings"], sort_keys=True).encode()
            ).hexdigest()
        except Exception:
            self.close()
            raise

    def process(self, source):
        import numpy as np

        from colorcorrection.classic_face_inference import decide, measure_source, pixel_hash
        from colorcorrection.levels_operator import apply_rgb_lut

        measured = measure_source(source, self.detector)
        try:
            lut, decision = decide(measured, self.model)
        except RuntimeError as exc:
            if (
                self.preference != "auto"
                or not self.device.startswith("cuda")
                or not any(
                    token in str(exc).lower()
                    for token in ("cuda", "cudnn", "cublas", "out of memory")
                )
            ):
                raise
            from colorcorrection.classic_face_inference import load_face_controller

            self.emit("GPU стала недоступна. Продолжаю ту же V39 на CPU…")
            self.model = load_face_controller(
                Path(self.config["checkpoint"]), self.config["checkpoint_sha256"], device="cpu"
            )
            self.device, self.device_name = "cpu", "Процессор · CPU · V39"
            lut, decision = decide(measured, self.model)
        output = apply_rgb_lut(source, lut)
        h, w = source.shape[:2]
        unchanged = np.array_equal(source, output)
        boxes = measured["boxes"]
        reason = "no_pixel_changes" if unchanged else "face_not_found" if not boxes else None
        return output, dict(
            status="needs_attention" if reason else "corrected",
            reason=reason,
            corrected_faces=len(boxes),
            faces=[
                dict(
                    native_bbox=[round(b[0] * w), round(b[1] * h), round(b[2] * w), round(b[3] * h)]
                )
                for b in boxes
            ],
            decision=decision,
            width=w,
            height=h,
            full_geometry=True,
            source_only=True,
            output_pixel_sha256=pixel_hash(output),
            model="v39-epoch005-raw",
            processing_device=self.device_name,
        )

    def close(self):
        self.model = self.detector = None
        import sys

        if "torch" in sys.modules:
            torch = sys.modules["torch"]
            if torch.cuda.is_initialized():
                try:
                    torch.cuda.empty_cache()
                except RuntimeError:
                    pass  # The report/lock still need finalisation after device loss.
        if self.lease is not None:
            self.lease.close()
            self.lease = None
