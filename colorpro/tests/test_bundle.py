import json
from pathlib import Path

import pytest

from colorpro.config import V39_SHA256, load_config


def test_portable_bundle_paths_and_state(monkeypatch, tmp_path):
    bundle = tmp_path / "arbitrary install directory" / "payload"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(
        json.dumps(
            dict(
                schema="colorpro-bundle-v1",
                source_checkpoint_sha256=V39_SHA256,
                platform="win10",
                files={"weights/v39.pt": "0" * 64},
            )
        ),
        encoding="utf8",
    )
    monkeypatch.setenv("COLORPRO_BUNDLE", str(bundle))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-profile"))
    config = load_config()
    assert Path(config["checkpoint"]) == bundle / "weights/v39.pt"
    assert Path(config["state_root"]) == tmp_path / "user-profile/ColorPro"
    assert config["source_checkpoint_sha256"] == V39_SHA256
    assert str(bundle) in config["protected_roots"]


def test_bundle_does_not_accept_external_files(monkeypatch, tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            dict(
                schema="colorpro-bundle-v1",
                source_checkpoint_sha256=V39_SHA256,
                platform="win7",
                files={"weights/v39.pt": "0" * 64, "../external.py": "1" * 64},
            )
        ),
        encoding="utf8",
    )
    monkeypatch.setenv("COLORPRO_BUNDLE", str(tmp_path))
    with pytest.raises(ValueError):
        load_config()
