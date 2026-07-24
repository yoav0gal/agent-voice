import threading

import numpy as np
import pytest

from kokoro_cli.client import ServiceUnavailable, health_check, request_speech
from kokoro_cli.config import update_defaults
from kokoro_cli.engine import Speech
from kokoro_cli.service import create_server, serve, validate_payload


def test_openai_shaped_payload_is_validated():
    request = validate_payload(
        {"input": "hello", "voice": "af_heart", "speed": 1, "response_format": "MP3"}
    )
    assert request.text == "hello"
    assert request.speed == 1.0
    assert request.audio_format == "mp3"
    assert request.play is False


def test_payload_uses_saved_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path))
    update_defaults(voice="bf_emma", speed=1.15)

    request = validate_payload({"input": "hello"})

    assert request.voice == "bf_emma"
    assert request.speed == 1.15


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"input": None}, "input must be a string"),
        ({"input": "hello", "speed": None}, "speed must be a number"),
        ({"input": "hello", "play": "false"}, "play must be a boolean"),
        ({"input": "hello", "response_format": "flac"}, "response_format must be"),
    ],
)
def test_bad_payloads_are_rejected(payload, message):
    with pytest.raises(ValueError, match=message):
        validate_payload(payload)


def test_remote_bind_is_rejected():
    with pytest.raises(ValueError, match="only binds to localhost"):
        serve(object(), "0.0.0.0", 8765)


def test_health_and_speech_contract(tmp_path):
    class FakeEngine:
        variant = "int8"

        def voices(self):
            return ["af_heart"]

        def synthesize(self, text, voice, speed, lang):
            assert text == "hello from the client"
            return Speech(np.zeros(2_400, dtype=np.float32), 24_000, 0.01)

    server = create_server(FakeEngine(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        health = health_check(url)
        result = request_speech(
            url,
            "hello from the client",
            tmp_path / "service.wav",
            "wav",
            "af_heart",
            1.0,
            "en-us",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert health["service"] == "kokoro"
    assert health["variant"] == "int8"
    assert result["backend"] == "service"
    assert result["speed"] == 1.0
    assert result["sample_rate"] == 24_000
    assert result["duration_seconds"] == 0.1
    assert (tmp_path / "service.wav").stat().st_size > 44


def test_health_rejects_a_non_kokoro_service(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"status":"ok"}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(ServiceUnavailable, match="invalid response"):
        health_check("http://127.0.0.1:8765")
