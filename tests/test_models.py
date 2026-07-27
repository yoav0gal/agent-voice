from __future__ import annotations

import hashlib
import io
import threading

import pytest

from agent_voice import kokoro as kokoro_module
from agent_voice import paths as paths_module
from agent_voice.kokoro import KOKORO_VARIANTS, KokoroAdapter
from agent_voice.model import ModelSelection
from agent_voice.paths import project_root
from agent_voice.registry import MODEL_REGISTRY


def test_default_model_is_compact_int8():
    descriptor = KokoroAdapter().descriptor

    assert descriptor.selection == ModelSelection("kokoro", "int8")
    assert KOKORO_VARIANTS == ("int8", "fp16", "full")


def test_registry_is_the_model_composition_root():
    assert MODEL_REGISTRY.model_ids == ("kokoro",)
    assert MODEL_REGISTRY.select() == ModelSelection("kokoro", "int8")
    assert MODEL_REGISTRY.select("kokoro", "fp16") == ModelSelection("kokoro", "fp16")
    assert isinstance(
        MODEL_REGISTRY.create(ModelSelection("kokoro", "full")),
        KokoroAdapter,
    )


def test_unknown_model_is_rejected():
    try:
        KokoroAdapter(ModelSelection("kokoro", "tiny"))
    except ValueError as error:
        assert "Unknown Kokoro variant" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_setup_prepares_assets_once_per_adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_MODEL_DIR", str(tmp_path))
    downloads = []

    def download(asset, destination, force):
        downloads.append((asset[0], destination, force))

    monkeypatch.setattr(kokoro_module, "_download_asset", download)
    model = KokoroAdapter(ModelSelection("kokoro", "int8"))

    first = model.setup()
    second = model.setup()

    assert first == second
    assert [item[0] for item in downloads] == [
        "kokoro-v1.0.int8.onnx",
        "voices-v1.0.bin",
    ]
    assert all(item[1].parent == tmp_path for item in downloads)


def test_windows_uses_local_app_data(tmp_path, monkeypatch):
    installed_module = tmp_path / "site-packages" / "agent_voice" / "paths.py"
    installed_module.parent.mkdir(parents=True)
    installed_module.touch()
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.delenv("AGENT_VOICE_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(paths_module, "__file__", str(installed_module))
    monkeypatch.setattr(paths_module.sys, "platform", "win32")

    assert project_root() == (local_app_data / "agent-voice").resolve()


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

    monkeypatch.setattr(kokoro_module.urllib.request, "urlopen", urlopen)
    errors = []

    def download():
        try:
            kokoro_module._download_asset(asset, destination, False)
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


def test_failed_download_preserves_destination_and_removes_partial_file(
    tmp_path, monkeypatch
):
    destination = tmp_path / "tiny.onnx"
    destination.write_bytes(b"existing model")
    payload = b"incomplete"
    asset = (
        destination.name,
        len(payload) + 1,
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(
        kokoro_module.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(payload),
    )

    with pytest.raises(RuntimeError, match="size mismatch"):
        kokoro_module._download_asset(asset, destination, True)

    assert destination.read_bytes() == b"existing model"
    assert list(tmp_path.glob("*.part")) == []
