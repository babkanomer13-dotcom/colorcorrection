import pytest

from colorpro import detector_path


def test_ascii_path_unchanged(tmp_path):
    path = tmp_path / "yunet.onnx"
    with detector_path.compatible_model_path(path) as actual:
        assert actual == path


def test_short_parent_preserves_onnx_suffix(tmp_path, monkeypatch):
    path = tmp_path / "Андрей" / "yunet.onnx"
    monkeypatch.setattr(detector_path, "short_path", lambda _: tmp_path / "ASCII")
    with detector_path.compatible_model_path(path) as actual:
        assert actual == tmp_path / "ASCII/yunet.onnx"


def test_unicode_without_short_paths_has_private_temporary_copy(tmp_path, monkeypatch):
    path = tmp_path / "Андрей" / "yunet.onnx"
    path.parent.mkdir()
    path.write_bytes(b"synthetic detector, not a real ONNX model")
    monkeypatch.setattr(detector_path, "short_path", lambda _: None)
    monkeypatch.setattr(detector_path, "cache_parents", lambda: iter([path.parent, tmp_path]))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with detector_path.compatible_model_path(path) as actual:
            assert str(actual).isascii() and actual.read_bytes() == path.read_bytes()
            temporary = actual.parent
            raise RuntimeError("synthetic failure")
    assert path.is_file() and not temporary.exists()
    assert not list(tmp_path.glob("ColorPro-model-*"))
