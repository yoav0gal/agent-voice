from __future__ import annotations

import errno
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_voice import viewer as viewer_module
from agent_voice import viewer_server
from agent_voice import controls as controls_module
from agent_voice.media import CONTENT_TYPES, generating_audio
from agent_voice.paths import pending_generation_path, streaming_pcm_path
from agent_voice.viewer import (
    VIEWER_PROTOCOL,
    Viewer,
    delete_expired_recordings,
    ensure_viewer,
    publish_language,
    publish_control,
    publish_player,
    publish_recording,
    publish_source,
    recording_player_url,
    recording_stream_url,
    recording_urls,
    recording_control_urls,
    source_path,
    stop_viewer,
)
from agent_voice.viewer_server import DEFAULT_VIEWER_PORT, Handler, Server


@contextmanager
def _running_viewer(recordings: Path):
    server = Server(recordings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    ("name", "content_type"),
    [
        ("sample.wav", "audio/wav"),
        ("sample.mp3", "audio/mpeg"),
        ("sample.opus", "audio/ogg"),
        ("sample.m4a", "audio/mp4"),
    ],
)
def test_viewer_serves_supported_audio_and_dynamic_player(tmp_path, name, content_type):
    recording = tmp_path / name
    recording.write_bytes(b"0123456789")
    narration = 'Visible response.\n<script>alert("no")</script>'
    publish_source(recording, narration)
    player_name = publish_player(recording)

    with _running_viewer(tmp_path) as (_, url):
        with urllib.request.urlopen(f"{url}/recordings/{name}") as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == content_type
            assert response.read() == b"0123456789"

        with urllib.request.urlopen(f"{url}/player/{player_name}") as response:
            document = response.read().decode()
            assert response.headers["Content-Type"] == "text/html; charset=utf-8"
            assert '<audio controls preload="metadata">' in document
            assert f'src="/recordings/{name}"' in document
            assert f'type="{content_type}"' in document
            assert f"<title>{name} · Agent Voice</title>" in document
            assert 'rel="icon"' in document
            assert 'type="image/svg+xml"' in document
            assert 'href="data:image/svg+xml;base64,' in document
            assert document.count('src="data:image/svg+xml;base64,') == 1
            assert "<h1>Agent Voice</h1>" in document
            assert "<summary>Narration text</summary>" in document
            assert 'class="narration">Visible response.\n&lt;script&gt;' in document
            assert "white-space: pre-wrap" in document
            assert "prefers-color-scheme: dark" in document
            assert "&lt;script&gt;" in document
            assert "<script>" not in document

    assert recording.is_file()
    assert source_path(recording).read_text() == narration


@pytest.mark.parametrize("name", ("live.wav", "live.mp3", "live.opus", "live.m4a"))
def test_player_uses_native_live_audio_while_recording_is_generated(tmp_path, name):
    recording = tmp_path / name
    recording.touch()
    publish_source(recording, "Live response")
    player_name = publish_player(recording)
    pending_generation_path(recording).touch()
    streaming_pcm_path(recording).touch()

    with _running_viewer(tmp_path) as (_, url):
        with urllib.request.urlopen(f"{url}/player/{player_name}") as response:
            document = response.read().decode()
        assert f'src="/stream/{name}"' in document
        assert 'type="audio/wav"' in document
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"{url}/recordings/{name}")
        assert error.value.code == 425

        def finish_generation():
            time.sleep(0.05)
            streaming_pcm_path(recording).write_bytes(b"\x01\x00\x02\x00")
            recording.write_bytes(b"final audio")
            pending_generation_path(recording).unlink()

        writer = threading.Thread(target=finish_generation)
        writer.start()
        with urllib.request.urlopen(f"{url}/stream/{name}") as response:
            audio = response.read()
            assert response.headers["Content-Type"] == "audio/wav"
        writer.join(timeout=1)

        with urllib.request.urlopen(f"{url}/stream/{name}") as response:
            assert response.url == f"{url}/stream/{name}"
            assert response.status == 200
            assert (
                response.headers["Content-Type"] == CONTENT_TYPES[name.split(".")[-1]]
            )
            assert response.read() == b"final audio"
        assert streaming_pcm_path(recording).is_file()

    assert audio[:4] == b"RIFF"
    assert audio[8:12] == b"WAVE"
    assert audio[44:] == b"\x01\x00\x02\x00"


def test_viewer_rejects_legacy_player_links(tmp_path):
    recording = tmp_path / "legacy.mp3"
    recording.write_bytes(b"audio")

    with _running_viewer(tmp_path) as (_, url):
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(f"{url}/player/legacy.mp3")

    assert rejected.value.code == 404


def test_player_urls_keep_audio_formats_distinct(tmp_path):
    viewer = Viewer(tmp_path, 49123, 123)
    mp3 = tmp_path / "sample.mp3"
    wav = tmp_path / "sample.wav"
    mp3.write_bytes(b"mp3")
    wav.write_bytes(b"wav")

    publish_source(mp3, "MP3")
    publish_source(wav, "WAV")
    mp3_name = publish_player(mp3)
    wav_name = publish_player(wav)
    mp3_url = recording_player_url(viewer, mp3_name)
    wav_url = recording_player_url(viewer, wav_name)
    _, mp3_audio_url = recording_urls(viewer, mp3, mp3_name)
    _, wav_audio_url = recording_urls(viewer, wav, wav_name)
    mp3_stream_url = recording_stream_url(viewer, mp3)

    assert mp3_url.endswith("/player/sample.html")
    assert wav_url.endswith("/player/sample-2.html")
    assert mp3_audio_url.endswith("/recordings/sample.mp3")
    assert wav_audio_url.endswith("/recordings/sample.wav")
    assert mp3_stream_url.endswith("/stream/sample.mp3")
    with _running_viewer(tmp_path) as (_, url):
        with urllib.request.urlopen(f"{url}/player/sample.html") as response:
            assert 'src="/recordings/sample.mp3"' in response.read().decode()
        with urllib.request.urlopen(f"{url}/player/sample-2.html") as response:
            assert 'src="/recordings/sample.wav"' in response.read().decode()


def test_recording_control_url_toggles_one_nonblocking_player(tmp_path, monkeypatch):
    recording = tmp_path / "sample.mp3"
    recording.write_bytes(b"audio")
    control_token = publish_control(recording)
    calls = []

    class Playback:
        def control(self, path, action):
            calls.append((path, action))
            playing = len(calls) % 2 == 1
            return SimpleNamespace(to_dict=lambda: {"playing": playing})

        def close(self):
            pass

    monkeypatch.setattr(viewer_server, "PlaybackController", Playback)

    with _running_viewer(tmp_path) as (server, url):
        viewer = Viewer(tmp_path, server.server_port, 123)
        monkeypatch.setattr(controls_module, "active_viewer", lambda: viewer)
        control_url = recording_control_urls(control_token)["toggle"]
        assert controls_module.trigger_control_url(control_url) == {"playing": True}
        assert controls_module.trigger_control_url(control_url) == {"playing": False}
        request = urllib.request.Request(
            f"{url}/control/{control_token}/toggle", method="HEAD"
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request)
        assert rejected.value.code == 405

        request = urllib.request.Request(
            f"{url}/control/{control_token}/toggle",
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request)
        assert rejected.value.code == 403

        request = urllib.request.Request(
            f"{url}/control/{control_token}/delete",
            headers={"X-Agent-Voice-Control": "1"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request)
        assert rejected.value.code == 404

    assert calls == [
        (recording.resolve(), "toggle"),
        (recording.resolve(), "toggle"),
    ]


def test_viewer_starts_or_schedules_local_playback(tmp_path, monkeypatch):
    recording = tmp_path / "sample.mp3"
    recording.write_bytes(b"audio")
    calls = []
    played = threading.Event()

    class Playback:
        def control(self, path, action):
            calls.append((path, action))
            played.set()
            return SimpleNamespace(to_dict=lambda: {"playing": True})

        def close(self):
            pass

    monkeypatch.setattr(viewer_server, "PlaybackController", Playback)
    with _running_viewer(tmp_path) as (_, url):
        headers = {"X-Agent-Voice-Playback": "1"}
        request = urllib.request.Request(
            f"{url}/play/sample.mp3", headers=headers, method="POST"
        )
        with urllib.request.urlopen(request) as response:
            assert json.loads(response.read()) == {"state": "started", "playing": True}

        with urllib.request.urlopen(request) as response:
            assert json.loads(response.read()) == {"state": "started", "playing": True}

        played.clear()
        request = urllib.request.Request(
            f"{url}/play/sample.mp3?after=0.01", headers=headers, method="POST"
        )
        with urllib.request.urlopen(request) as response:
            assert json.loads(response.read()) == {
                "state": "scheduled",
                "starts_in_seconds": 0.01,
            }
        assert played.wait(timeout=1)

    assert calls == [(recording.resolve(), "restart")] * 3


def test_rejected_control_probe_does_not_regenerate_missing_audio(
    tmp_path, monkeypatch
):
    recording = tmp_path / "missing.mp3"
    control_token = publish_control(recording)
    monkeypatch.setattr(
        viewer_server,
        "_regenerate_recording",
        lambda _path: (_ for _ in ()).throw(AssertionError("unexpected regeneration")),
    )

    with _running_viewer(tmp_path) as (server, _url):
        control_url = (
            f"http://127.0.0.1:{server.server_port}/control/{control_token}/toggle"
        )
        request = urllib.request.Request(
            control_url,
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request)
        assert rejected.value.code == 403


def test_viewer_supports_head(tmp_path):
    recording = tmp_path / "range.mp3"
    recording.write_bytes(b"0123456789")

    with _running_viewer(tmp_path) as (_, url):
        head = urllib.request.Request(
            f"{url}/recordings/range.mp3",
            method="HEAD",
        )
        with urllib.request.urlopen(head) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == "10"
            assert response.headers["Accept-Ranges"] == "bytes"
            assert response.read() == b""


@pytest.mark.parametrize(
    ("requested_range", "expected_range", "expected_body"),
    [
        ("bytes=2-5", "bytes 2-5/10", b"2345"),
        ("bytes=7-", "bytes 7-9/10", b"789"),
        ("bytes=-3", "bytes 7-9/10", b"789"),
        ("bytes=8-20", "bytes 8-9/10", b"89"),
    ],
)
def test_viewer_streams_single_audio_ranges(
    tmp_path, requested_range, expected_range, expected_body
):
    recording = tmp_path / "range.mp3"
    recording.write_bytes(b"0123456789")

    with _running_viewer(tmp_path) as (_, url):
        request = urllib.request.Request(
            f"{url}/recordings/range.mp3",
            headers={"Range": requested_range},
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 206
            assert response.headers["Accept-Ranges"] == "bytes"
            assert response.headers["Content-Range"] == expected_range
            assert response.headers["Content-Length"] == str(len(expected_body))
            assert response.read() == expected_body


def test_viewer_rejects_unsatisfiable_audio_ranges(tmp_path):
    recording = tmp_path / "range.mp3"
    recording.write_bytes(b"0123456789")

    with _running_viewer(tmp_path) as (_, url):
        request = urllib.request.Request(
            f"{url}/recordings/range.mp3",
            headers={"Range": "bytes=20-30"},
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request)

    assert rejected.value.code == 416
    assert rejected.value.headers["Accept-Ranges"] == "bytes"
    assert rejected.value.headers["Content-Range"] == "bytes */10"


def test_viewer_supports_head_for_an_audio_range(tmp_path):
    recording = tmp_path / "range.mp3"
    recording.write_bytes(b"0123456789")

    with _running_viewer(tmp_path) as (_, url):
        request = urllib.request.Request(
            f"{url}/recordings/range.mp3",
            headers={"Range": "bytes=2-5"},
            method="HEAD",
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == "bytes 2-5/10"
            assert response.headers["Content-Length"] == "4"
            assert response.read() == b""


@pytest.mark.parametrize(
    "path",
    [
        "/recordings/../secret.mp3",
        "/recordings/%2e%2e%2fsecret.mp3",
        "/recordings/%00.mp3",
        "/recordings/secret.txt",
        "/recordings/missing.mp3",
        "/recordings/sample.mp3?download=1",
        "/player/missing.html",
    ],
)
def test_viewer_rejects_paths_outside_supported_recordings(tmp_path, path):
    (tmp_path / "sample.mp3").write_bytes(b"audio")

    with _running_viewer(tmp_path) as (_, url):
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(f"{url}{path}")
        assert rejected.value.code == 404


def test_viewer_rejects_host_header(tmp_path):
    with _running_viewer(tmp_path) as (server, url):
        hostile = urllib.request.Request(
            f"{url}/health",
            headers={"Host": f"attacker.example:{server.server_port}"},
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(hostile)
        assert rejected.value.code == 403


def test_viewer_prefers_stable_port(tmp_path, monkeypatch):
    ports = []

    class FakeServer:
        def __init__(self, recordings, port=0):
            ports.append(port)

    monkeypatch.setattr(viewer_server, "Server", FakeServer)

    viewer_server.create_server(tmp_path)

    assert ports == [DEFAULT_VIEWER_PORT]


def test_viewer_binding_does_not_resolve_localhost(tmp_path, monkeypatch):
    def unexpected_lookup(host):
        raise AssertionError(f"Unexpected DNS lookup for {host}")

    monkeypatch.setattr(socket, "getfqdn", unexpected_lookup)

    with Server(tmp_path) as server:
        assert server.server_name == "127.0.0.1"
        assert server.server_port > 0


def test_viewer_cleans_at_startup_and_every_hour(tmp_path, monkeypatch):
    calls = []
    now = [100.0]
    monkeypatch.setattr(
        viewer_server,
        "delete_expired_recordings",
        lambda recordings: calls.append(recordings),
    )
    monkeypatch.setattr(viewer_server.time, "monotonic", lambda: now[0])

    with Server(tmp_path) as server:
        assert calls == []
        server.service_actions()
        now[0] += 60 * 60 - 1
        server.service_actions()
        now[0] += 1
        server.service_actions()
        server.service_actions()

    assert calls == [tmp_path.resolve(), tmp_path.resolve()]


def test_viewer_falls_back_when_stable_port_is_busy(tmp_path, monkeypatch):
    ports = []

    class FakeServer:
        def __init__(self, recordings, port=0):
            ports.append(port)
            if port == DEFAULT_VIEWER_PORT:
                raise OSError(errno.EADDRINUSE, "busy")

    monkeypatch.setattr(viewer_server, "Server", FakeServer)

    viewer_server.create_server(tmp_path)

    assert ports == [DEFAULT_VIEWER_PORT, 0]


def test_publish_recording_copies_external_audio_without_html(tmp_path):
    source = tmp_path / "exports" / "voice"
    source.parent.mkdir()
    source.write_bytes(b"opus")
    managed = tmp_path / "managed"

    published = publish_recording(source, "opus", managed)

    assert published == managed / "voice.opus"
    assert published.read_bytes() == b"opus"
    assert list(managed.iterdir()) == [published]


def test_expired_recordings_keep_sources_and_unmanaged_audio(tmp_path):
    now = time.time()
    delete_after = (4 * 24 + 18) * 60 * 60
    expired = tmp_path / "expired.mp3"
    fresh = tmp_path / "fresh.mp3"
    unmanaged = tmp_path / "unmanaged.mp3"
    unrelated_sidecar = tmp_path / "unrelated.mp3"
    for recording in (expired, fresh, unmanaged, unrelated_sidecar):
        recording.write_bytes(b"audio")
    publish_source(expired, "Editable old text.")
    publish_player(expired)
    publish_language(expired, "en-us")
    publish_source(fresh, "Editable fresh text.")
    publish_player(fresh)
    publish_language(fresh, "en-us")
    publish_source(unrelated_sidecar, "Not Agent Voice metadata.")
    os.utime(expired, (now - delete_after - 1,) * 2)
    os.utime(fresh, (now - delete_after + 1,) * 2)
    os.utime(unrelated_sidecar, (now - 6 * 24 * 60 * 60,) * 2)

    delete_expired_recordings(tmp_path, now=now)

    assert not expired.exists()
    assert source_path(expired).read_text() == "Editable old text."
    assert fresh.is_file()
    assert unmanaged.is_file()
    assert unrelated_sidecar.is_file()


def test_completed_stream_sidecars_expire_without_touching_active_generation(tmp_path):
    now = time.time()
    completed = tmp_path / "completed.mp3"
    active = tmp_path / "active.mp3"
    stale = tmp_path / "stale.mp3"
    for recording in (completed, active, stale):
        recording.touch()
        streaming_pcm_path(recording).write_bytes(b"pcm")
        os.utime(
            streaming_pcm_path(recording),
            (now - 60 * 60 - 1,) * 2,
        )
    pending_generation_path(active).touch()
    os.utime(
        pending_generation_path(active),
        (now - 60 * 60 - 1,) * 2,
    )
    pending_generation_path(stale).touch()
    stale.write_bytes(generating_audio("mp3"))
    os.utime(
        pending_generation_path(stale),
        (now - 6 * 60 * 60 - 1,) * 2,
    )

    delete_expired_recordings(tmp_path, now=now)

    assert not streaming_pcm_path(completed).exists()
    assert streaming_pcm_path(active).is_file()
    assert not stale.exists()
    assert not pending_generation_path(stale).exists()
    assert not streaming_pcm_path(stale).exists()


def test_viewer_regenerates_missing_audio_from_source(tmp_path, monkeypatch):
    recording = tmp_path / "requested.mp3"
    publish_source(recording, "Current editable text.")
    publish_player(recording)
    publish_language(recording, "en-us")
    regenerated = []

    def regenerate(path):
        regenerated.append(source_path(path).read_text())
        path.write_bytes(b"regenerated")

    monkeypatch.setattr(viewer_server, "_regenerate_recording", regenerate)

    with _running_viewer(tmp_path) as (_, url):
        with urllib.request.urlopen(f"{url}/recordings/requested.mp3") as response:
            assert response.read() == b"regenerated"

    assert regenerated == ["Current editable text."]


def test_viewer_retries_when_cleanup_removes_audio_before_open(tmp_path, monkeypatch):
    recording = tmp_path / "requested.mp3"
    recording.write_bytes(b"expired")
    publish_source(recording, "Current editable text.")
    publish_player(recording)
    publish_language(recording, "en-us")
    monkeypatch.setattr(
        viewer_server,
        "_regenerate_recording",
        lambda path: path.write_bytes(b"regenerated"),
    )
    send_file = Handler._send_file
    first = [True]

    def remove_before_open(self, path, content_type, head):
        if first[0]:
            first[0] = False
            path.unlink()
        return send_file(self, path, content_type, head)

    monkeypatch.setattr(Handler, "_send_file", remove_before_open)

    with _running_viewer(tmp_path) as (_, url):
        with urllib.request.urlopen(f"{url}/recordings/requested.mp3") as response:
            assert response.read() == b"regenerated"


def test_viewer_reports_regeneration_failure(tmp_path, monkeypatch):
    recording = tmp_path / "requested.mp3"
    publish_source(recording, "Current editable text.")
    publish_player(recording)
    publish_language(recording, "en-us")
    monkeypatch.setattr(
        viewer_server,
        "_regenerate_recording",
        lambda _path: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    with _running_viewer(tmp_path) as (_, url):
        with pytest.raises(urllib.error.HTTPError) as failed:
            urllib.request.urlopen(f"{url}/recordings/requested.mp3")

    assert failed.value.code == 503


def test_regeneration_uses_saved_language_and_current_voice(tmp_path, monkeypatch):
    recording = tmp_path / "requested.mp3"
    publish_source(recording, "שלום")
    publish_language(recording, "he-il")
    requests = []
    writes = []

    class Model:
        def synthesize(self, request):
            requests.append(request)
            return SimpleNamespace(samples=[0.0], sample_rate=24_000)

    class Registry:
        def select(self):
            return "current-model"

        def create(self, selection):
            assert selection == "current-model"
            return Model()

    monkeypatch.setattr(viewer_server, "MODEL_REGISTRY", Registry())
    monkeypatch.setattr(
        viewer_server,
        "load_defaults",
        lambda: SimpleNamespace(voice="bf_emma", speed=1.2),
    )
    monkeypatch.setattr(
        viewer_server,
        "write_audio",
        lambda samples, rate, path, audio_format: writes.append(
            (samples, rate, path, audio_format)
        ),
    )

    viewer_server._regenerate_recording(recording)

    assert requests[0].text == "שלום"
    assert requests[0].language == "he-il"
    assert requests[0].voice.name == "bf_emma"
    assert requests[0].speed == 1.2
    assert writes == [([0.0], 24_000, recording, "mp3")]


def test_running_rejects_old_viewer_protocol(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"service": "agent-voice-viewer", "pid": 123}).encode()

    monkeypatch.setattr(
        viewer_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(),
    )
    state = {"port": 8779, "pid": 123, "recordings_dir": str(tmp_path)}

    assert viewer_module._running(state) is None
    assert viewer_module._running(state, require_protocol=False) == Viewer(
        tmp_path.resolve(), 8779, 123
    )


def test_dynamic_viewer_process_start_status_and_stop(tmp_path, monkeypatch):
    home = tmp_path / "home"
    recordings = tmp_path / "recordings"
    monkeypatch.setenv("AGENT_VOICE_HOME", str(home))

    try:
        started = ensure_viewer(recordings)
        assert started.running is True
        assert started.port is not None and started.port > 0
        assert started.url == f"http://127.0.0.1:{started.port}"
        assert started.recordings_dir == recordings.resolve()

        with urllib.request.urlopen(f"{started.url}/health") as response:
            health = json.loads(response.read())
        assert health["service"] == "agent-voice-viewer"
        assert health["protocol"] == VIEWER_PROTOCOL
    finally:
        stopped = stop_viewer()

    assert stopped.running is False


def test_viewer_starts_without_a_window_on_windows(tmp_path, monkeypatch):
    recordings = tmp_path / "recordings"
    viewer = Viewer(recordings.resolve(), 8779, 123)
    running = iter((None, None, viewer))
    captured = {}

    class Process:
        def poll(self):
            return None

    def popen(command, **options):
        captured["options"] = options
        return Process()

    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(viewer_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        viewer_module.subprocess, "CREATE_NO_WINDOW", 123, raising=False
    )
    monkeypatch.setattr(viewer_module, "_state", lambda: {})
    monkeypatch.setattr(
        viewer_module,
        "_running",
        lambda *_args, **_kwargs: next(running),
    )
    monkeypatch.setattr(viewer_module.subprocess, "Popen", popen)

    assert ensure_viewer(recordings) == viewer
    assert captured["options"]["creationflags"] == 123
    assert "start_new_session" not in captured["options"]
