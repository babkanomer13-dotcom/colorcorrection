import sys
from types import SimpleNamespace

import pytest

from colorpro import engine


def torch_stub(cards):
    def props(i):
        return SimpleNamespace(uuid=f"GPU-{i}", name=f"NVIDIA card {i}")

    return SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: bool(cards),
            device_count=lambda: len(cards),
            get_device_properties=props,
            mem_get_info=lambda i: (cards[i] * 1024**2, 24 * 1024**3),
        )
    )


def test_cpu_does_not_probe_cuda():
    assert engine.device_candidates(None, "cpu") == [("cpu", "Процессор · CPU")]


def test_auto_without_gpu_and_manual_gpu_error(monkeypatch):
    monkeypatch.setattr(engine, "inventory", lambda: [])
    assert engine.device_candidates(torch_stub([]), "auto")[0][0] == "cpu"
    with pytest.raises(RuntimeError, match="CPU"):
        engine.device_candidates(torch_stub([]), "cuda")


def test_best_available_card_not_hardcoded(monkeypatch):
    monkeypatch.setattr(engine, "inventory", lambda: [])
    choices = engine.device_candidates(torch_stub([1024, 8000]), "auto")
    assert [c[0] for c in choices] == ["cuda:1", "cuda:0", "cpu"]
    assert [c[0] for c in engine.device_candidates(torch_stub([1024, 8000]), "cuda")] == [
        "cuda:1",
        "cuda:0",
    ]


def test_busy_and_low_memory_cards_excluded(monkeypatch):
    monkeypatch.setattr(engine, "inventory", lambda: [["GPU-0", "Any NVIDIA", "4000", "99"]])
    assert engine.device_candidates(torch_stub([18000, 128]), "auto")[0][0] == "cpu"


def test_missing_smi_does_not_disable_cuda(monkeypatch):
    def missing():
        raise FileNotFoundError("No NVIDIA utility")

    monkeypatch.setattr(engine, "inventory", missing)
    assert engine.device_candidates(torch_stub([2000]), "auto")[0][0] == "cuda:0"


def test_broken_cuda_driver_auto_fallback(monkeypatch):
    monkeypatch.setattr(engine, "inventory", lambda: [])

    def broken():
        raise RuntimeError("CUDA initialisation failed")

    stub = torch_stub([2000])
    stub.cuda.is_available = broken
    assert engine.device_candidates(stub, "auto")[0][0] == "cpu"


@pytest.fixture
def model_environment(monkeypatch, tmp_path):
    config = dict(
        checkpoint="synthetic.pt",
        checkpoint_sha256="test",
        state_root=str(tmp_path),
        bindings={"synthetic.pt": "test"},
        detector="synthetic.onnx",
    )
    monkeypatch.setattr(engine, "load_config", lambda: config)
    monkeypatch.setattr(engine, "verify_runtime", lambda _: None)
    monkeypatch.setattr(
        engine,
        "device_candidates",
        lambda _, mode: (
            [("cuda:0", "NVIDIA test"), ("cpu", "CPU")]
            if mode == "auto"
            else [("cuda:0", "NVIDIA test")]
        ),
    )
    stub = SimpleNamespace(
        set_num_threads=lambda _: None,
        use_deterministic_algorithms=lambda _: None,
        backends=SimpleNamespace(
            cuda=SimpleNamespace(matmul=SimpleNamespace()), cudnn=SimpleNamespace()
        ),
        cuda=SimpleNamespace(is_initialized=lambda: False),
    )
    monkeypatch.setitem(sys.modules, "torch", stub)
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(setNumThreads=lambda _: None))
    monkeypatch.setitem(
        sys.modules,
        "colorcorrection.source_face_detector",
        SimpleNamespace(
            SourceFaceDetector=lambda _: object(),
        ),
    )
    loads = []

    class Model:
        def to(self, device):
            return self

    def load(*_, device, **kwargs):
        loads.append(device)
        return Model()

    def incompatible(_, model, device):
        if device.startswith("cuda"):
            raise RuntimeError("CUDA: no kernel image available")

    monkeypatch.setattr(engine, "warmup", incompatible)
    module = SimpleNamespace(load_face_controller=load)
    monkeypatch.setitem(sys.modules, "colorcorrection.classic_face_inference", module)
    return loads, module


def test_incompatible_gpu_falls_back_to_cpu(model_environment):
    loads, _ = model_environment
    runner = engine.Engine("v39", "auto")
    try:
        assert runner.device == "cpu"
        assert loads == ["cpu", "cpu"]
    finally:
        runner.close()


def test_explicit_gpu_does_not_silently_fallback(model_environment):
    with pytest.raises(RuntimeError, match="Выберите CPU"):
        engine.Engine("v39", "cuda")


def test_corrupt_model_is_not_treated_as_gpu_failure(model_environment):
    _, module = model_environment

    def corrupt(*args, **kwargs):
        raise ValueError("Controller checkpoint checksum mismatch")

    module.load_face_controller = corrupt
    with pytest.raises(ValueError, match="checksum"):
        engine.Engine("v39", "auto")
