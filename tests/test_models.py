from __future__ import annotations

import hashlib
import threading

from kokoro_cli import models as models_module
from kokoro_cli.models import MODEL_ASSETS, model_paths, project_root


def test_default_model_is_compact_int8():
    model, voices = model_paths()
    assert model.name == "kokoro-v1.0.int8.onnx"
    assert voices.name == "voices-v1.0.bin"
    assert MODEL_ASSETS["int8"][1] < 100_000_000
    assert len(MODEL_ASSETS["int8"][2]) == 64


def test_unknown_model_is_rejected():
    try:
        model_paths("tiny")
    except ValueError as error:
        assert "Unknown model variant" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_windows_uses_local_app_data(tmp_path, monkeypatch):
    installed_module = tmp_path / "site-packages" / "kokoro_cli" / "models.py"
    installed_module.parent.mkdir(parents=True)
    installed_module.touch()
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.delenv("KOKORO_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(models_module, "__file__", str(installed_module))
    monkeypatch.setattr(models_module.sys, "platform", "win32")

    assert project_root() == (local_app_data / "kokoro").resolve()


def test_concurrent_downloads_share_one_verified_asset(tmp_path, monkeypatch):
    payload = b"verified model bytes"
    asset = (
        "tiny.onnx",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
    )
    destination = tmp_path / asset[0]
    first_read_started = threading.Event()
    release_first_read = threading.Event()
    calls = []

    class Response:
        def __init__(self):
            self._returned = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, _size):
            if self._returned:
                return b""
            first_read_started.set()
            assert release_first_read.wait(timeout=5)
            self._returned = True
            return payload

    def urlopen(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr(models_module.urllib.request, "urlopen", urlopen)
    errors = []

    def download():
        try:
            models_module._download_asset(asset, destination, False)
        except Exception as error:  # pragma: no cover - surfaced by assertion below
            errors.append(error)

    first = threading.Thread(target=download)
    second = threading.Thread(target=download)
    first.start()
    assert first_read_started.wait(timeout=5)
    second.start()
    release_first_read.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not errors
    assert not first.is_alive()
    assert not second.is_alive()
    assert destination.read_bytes() == payload
    assert len(calls) == 1
