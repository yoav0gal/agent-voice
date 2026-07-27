import json
import subprocess
import threading
import time
import urllib.error
import urllib.request

import numpy as np
import pytest

from agent_voice import client
from agent_voice.client import (
    ServiceUnavailable,
    ensure_service,
    health_check,
    request_speech,
)
from agent_voice.config import update_defaults
from agent_voice.model import (
    ModelDescriptor,
    ModelSelection,
    NamedVoice,
    Speech,
    VoiceCatalog,
)
from agent_voice.service import create_server, serve, validate_payload


def test_openai_shaped_payload_is_validated():
    request = validate_payload(
        {"input": "hello", "voice": "af_heart", "speed": 1, "response_format": "MP3"}
    )
    assert request.text == "hello"
    assert request.speed == 1.0
    assert request.audio_format == "mp3"
    assert request.play is False


def test_payload_uses_saved_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    update_defaults(voice="bf_emma", speed=1.15, format="m4a")

    request = validate_payload({"input": "hello"})

    assert request.voice == "bf_emma"
    assert request.speed == 1.15
    assert request.audio_format == "m4a"


def test_legacy_payload_aliases_are_not_used(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    update_defaults(format="m4a")

    with pytest.raises(ValueError, match="input must be a string"):
        validate_payload({"text": "hello"})

    request = validate_payload({"input": "hello", "format": "wav"})
    assert request.audio_format == "m4a"


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


@pytest.mark.parametrize(
    "host_template",
    [
        "localhost:{port}?extra",
        "localhost:{port}#fragment",
        "user@localhost:{port}",
        "localhost:{port}/path",
        "localhost:{port}:extra",
        "localhost:{port},attacker.example",
        "localhost",
        "localhost:{wrong_port}",
    ],
)
def test_host_header_rejects_extra_or_mismatched_syntax(host_template):
    server = create_server(object(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/health",
        headers={
            "Host": host_template.format(port=port, wrong_port=port + 1),
        },
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request, timeout=1)
        assert rejected.value.code == 403
        assert json.loads(rejected.value.read())["error"] == "Host must be localhost"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_legacy_speak_endpoint_is_not_available():
    server = create_server(object(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/speak",
        data=b'{"input":"hello"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request, timeout=1)
        assert rejected.value.code == 404
        assert json.loads(rejected.value.read())["error"] == "Not found"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_health_and_speech_contract(tmp_path):
    class FakeModel:
        descriptor = ModelDescriptor(
            selection=ModelSelection("test-model", "test-variant"),
            display_name="Test Model",
            runtime="test-runtime",
            capabilities=frozenset(),
        )

        def voice_catalog(self):
            return VoiceCatalog(
                named=(NamedVoice("af_heart"),),
                default=NamedVoice("af_heart"),
                accepts_reference_audio=False,
            )

        def synthesize(self, request):
            assert request.text == "hello from the client"
            return Speech(np.zeros(2_400, dtype=np.float32), 24_000, 0.01)

    server = create_server(FakeModel(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        health = health_check(url)
        hostile_host = urllib.request.Request(
            f"{url}/health",
            headers={"Host": f"attacker.example:{server.server_port}"},
        )
        with pytest.raises(urllib.error.HTTPError) as hostile:
            urllib.request.urlopen(hostile_host, timeout=1)
        ensure_service(
            url,
            ModelSelection("test-model", "test-variant"),
            None,
        )
        assert server.idle_timeout_seconds is None
        ensure_service(
            url,
            ModelSelection("test-model", "test-variant"),
            2.5,
        )
        assert server.idle_timeout_seconds == 150
        unsafe_request = urllib.request.Request(
            f"{url}/v1/audio/speech",
            data=b'{"input":"browser request"}',
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as unsafe:
            urllib.request.urlopen(unsafe_request, timeout=1)
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

    assert health["service"] == "agent-voice"
    assert health["engine"] == "test-runtime"
    assert health["model"] == "Test Model"
    assert health["model_id"] == "test-model"
    assert health["variant"] == "test-variant"
    assert health["service_mode"] == "on"
    assert health["service_timeout_minutes"] is None
    assert hostile.value.code == 403
    assert json.loads(hostile.value.read())["error"] == "Host must be localhost"
    assert unsafe.value.code == 400
    assert (
        json.loads(unsafe.value.read())["error"]
        == "Content-Type must be application/json"
    )
    assert result["backend"] == "service"
    assert result["speed"] == 1.0
    assert result["sample_rate"] == 24_000
    assert result["duration_seconds"] == 0.1
    assert (tmp_path / "service.wav").stat().st_size > 44


def test_health_remains_available_while_speech_is_running(tmp_path):
    synthesis_started = threading.Event()
    finish_synthesis = threading.Event()
    speech_errors = []

    class BlockingModel:
        descriptor = ModelDescriptor(
            selection=ModelSelection("test-model", "test-variant"),
            display_name="Test Model",
            runtime="test-runtime",
            capabilities=frozenset(),
        )

        def synthesize(self, request):
            synthesis_started.set()
            assert finish_synthesis.wait(timeout=2)
            return Speech(np.zeros(2_400, dtype=np.float32), 24_000, 0.01)

    server = create_server(BlockingModel(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"

    def speak():
        try:
            request_speech(
                url,
                "hello from the client",
                tmp_path / "service.wav",
                "wav",
                "af_heart",
                1.0,
                "en-us",
            )
        except Exception as error:  # pragma: no cover - asserted below
            speech_errors.append(error)

    worker = threading.Thread(target=speak, daemon=True)
    worker.start()
    try:
        assert synthesis_started.wait(timeout=1)
        health = health_check(url, timeout=0.5)
        assert health["status"] == "ok"
    finally:
        finish_synthesis.set()
        worker.join(timeout=2)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert not speech_errors
    assert not worker.is_alive()


def test_idle_server_waits_for_an_active_request():
    request_started = threading.Event()
    finish_request = threading.Event()

    class BlockingModel:
        descriptor = ModelDescriptor(
            selection=ModelSelection("test-model", "test-variant"),
            display_name="Test Model",
            runtime="test-runtime",
            capabilities=frozenset(),
        )

        def voice_catalog(self):
            request_started.set()
            assert finish_request.wait(timeout=2)
            return VoiceCatalog(
                named=(NamedVoice("af_heart"),),
                default=NamedVoice("af_heart"),
                accepts_reference_audio=False,
            )

    server = create_server(BlockingModel(), "127.0.0.1", 0, idle_timeout_seconds=0.05)
    thread = threading.Thread(target=server.serve_until_idle, daemon=True)
    thread.start()
    request = threading.Thread(
        target=lambda: urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/voices", timeout=2
        ).read(),
        daemon=True,
    )
    request.start()
    try:
        assert request_started.wait(timeout=1)
        time.sleep(0.1)
        assert thread.is_alive()
    finally:
        finish_request.set()
        request.join(timeout=2)
        thread.join(timeout=2)
        server.server_close()

    assert not request.is_alive()
    assert not thread.is_alive()


def test_health_rejects_a_non_agent_voice_service(monkeypatch):
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


def test_idle_server_stops_after_timeout():
    class FakeModel:
        pass

    server = create_server(FakeModel(), "127.0.0.1", 0, idle_timeout_seconds=0.05)
    thread = threading.Thread(target=server.serve_until_idle, daemon=True)
    thread.start()
    thread.join(timeout=1)
    server.server_close()

    assert not thread.is_alive()


@pytest.mark.parametrize(
    ("idle_timeout", "message"),
    [
        (2.5, "2.5 minute idle timeout"),
        (None, "no idle timeout"),
    ],
)
def test_service_starts_detached_and_waits_for_health(
    tmp_path, monkeypatch, capsys, idle_timeout, message
):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    checks = 0
    captured = {}

    def check(*args, **kwargs):
        nonlocal checks
        checks += 1
        if checks == 1:
            raise ServiceUnavailable("not running")
        return {
            "status": "ok",
            "service": "agent-voice",
            "model_id": "kokoro",
            "variant": "int8",
        }

    class Process:
        returncode = None

        def poll(self):
            return None

    def popen(command, **options):
        captured["command"] = command
        captured["options"] = options
        return Process()

    monkeypatch.setattr(client, "health_check", check)
    configured = []
    monkeypatch.setattr(
        client,
        "_configure_service_lifecycle",
        lambda url, timeout: configured.append((url, timeout)),
    )
    monkeypatch.setattr(client.subprocess, "Popen", popen)
    monkeypatch.setattr(client.time, "sleep", lambda _: None)

    result = ensure_service(
        "http://127.0.0.1:9876",
        ModelSelection("kokoro", "int8"),
        idle_timeout,
        startup_timeout=1,
    )

    assert result["status"] == "ok"
    assert configured == [("http://127.0.0.1:9876", idle_timeout)]
    assert message in capsys.readouterr().err
    expected_command = [
        captured["command"][0],
        "-m",
        "agent_voice",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "9876",
        "--model-id",
        "kokoro",
        "--variant",
        "int8",
    ]
    if idle_timeout is not None:
        expected_command.extend(["--idle-timeout", str(idle_timeout)])
    assert captured["command"] == expected_command
    assert captured["options"]["stdin"] is subprocess.DEVNULL
    assert captured["options"]["stdout"] is subprocess.DEVNULL
    assert captured["options"]["stderr"] is subprocess.DEVNULL


def test_failed_service_startup_terminates_the_detached_process(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    monkeypatch.setattr(
        client,
        "health_check",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ServiceUnavailable("not running")
        ),
    )
    times = iter((0.0, 2.0))
    monkeypatch.setattr(client.time, "monotonic", lambda: next(times))
    events = []

    class Process:
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append(("wait", timeout))
            return 0

    monkeypatch.setattr(client.subprocess, "Popen", lambda *args, **kwargs: Process())

    with pytest.raises(ServiceUnavailable, match="did not become ready"):
        ensure_service(
            "http://127.0.0.1:9876",
            ModelSelection("kokoro", "int8"),
            2.5,
            startup_timeout=1,
        )

    assert events == ["terminate", ("wait", 2)]


def test_hung_service_process_is_killed_after_termination_timeout():
    events = []

    class Process:
        def poll(self):
            return None

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append(("wait", timeout))
            if events.count(("wait", timeout)) == 1:
                raise subprocess.TimeoutExpired("agent-voice", timeout)
            return 0

        def kill(self):
            events.append("kill")

    client._terminate_process(Process())

    assert events == [
        "terminate",
        ("wait", 2),
        "kill",
        ("wait", 2),
    ]


def test_running_service_with_another_model_is_not_reused(monkeypatch):
    monkeypatch.setattr(
        client,
        "health_check",
        lambda *args, **kwargs: {
            "status": "ok",
            "service": "agent-voice",
            "model_id": "kokoro",
            "variant": "int8",
        },
    )
    monkeypatch.setattr(
        client.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("mismatched service must not be reused"),
    )

    with pytest.raises(ServiceUnavailable, match="requested kokoro/fp16"):
        ensure_service(
            "http://127.0.0.1:9876",
            ModelSelection("kokoro", "fp16"),
            2.5,
            startup_timeout=1,
        )


def test_speech_request_rejects_a_mismatched_running_model(tmp_path, monkeypatch):
    monkeypatch.setattr(
        client,
        "health_check",
        lambda *args, **kwargs: {
            "status": "ok",
            "service": "agent-voice",
            "model_id": "kokoro",
            "variant": "int8",
        },
    )
    monkeypatch.setattr(
        client.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("mismatch must fail before synthesis"),
    )

    with pytest.raises(ServiceUnavailable, match="requested kokoro/fp16"):
        request_speech(
            "http://127.0.0.1:9876",
            "hello",
            tmp_path / "speech.wav",
            "wav",
            "af_heart",
            1.0,
            "en-us",
            selection=ModelSelection("kokoro", "fp16"),
        )
