from __future__ import annotations

import errno
import json
import socket
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_voice.viewer import (
    Viewer,
    ensure_viewer,
    publish_player,
    publish_recording,
    recording_urls,
    stop_viewer,
    transcript_path,
)
from agent_voice import viewer_server
from agent_voice.viewer_server import DEFAULT_VIEWER_PORT, Server


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
def test_viewer_serves_supported_audio_and_dynamic_player(
    tmp_path, name, content_type
):
    recording = tmp_path / name
    recording.write_bytes(b"0123456789")
    player_name = publish_player(
        recording,
        'Visible <script>alert("no")</script> response.',
    )

    with _running_viewer(tmp_path) as (_, url):
        with urllib.request.urlopen(f"{url}/recordings/{name}") as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == content_type
            assert response.read() == b"0123456789"

        with urllib.request.urlopen(
            f"{url}/player/{player_name}"
        ) as response:
            document = response.read().decode()
            assert response.headers["Content-Type"] == "text/html; charset=utf-8"
            assert "<audio controls preload=\"metadata\">" in document
            assert f'src="/recordings/{name}"' in document
            assert f'type="{content_type}"' in document
            assert f"<title>{name} · Agent Voice</title>" in document
            assert 'rel="icon"' in document
            assert 'type="image/svg+xml"' in document
            assert 'href="data:image/svg+xml;base64,' in document
            assert 'class="brand-logo"' in document
            assert 'class="recording-icon"' in document
            assert document.count('src="data:image/svg+xml;base64,') == 2
            assert '<h2 id="response-heading">Response</h2>' in document
            assert "&lt;script&gt;" in document
            assert "<script>" not in document

    assert recording.is_file()
    assert transcript_path(recording).is_file()
    assert transcript_path(recording).read_text() == (
        'Visible <script>alert("no")</script> response.'
    )


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

    mp3_name = publish_player(mp3, "MP3")
    wav_name = publish_player(wav, "WAV")
    mp3_url, _ = recording_urls(viewer, mp3, mp3_name)
    wav_url, _ = recording_urls(viewer, wav, wav_name)

    assert mp3_url.endswith("/player/sample.html")
    assert wav_url.endswith("/player/sample-2.html")

    with _running_viewer(tmp_path) as (_, url):
        with urllib.request.urlopen(f"{url}/player/sample.html") as response:
            assert 'src="/recordings/sample.mp3"' in response.read().decode()
        with urllib.request.urlopen(f"{url}/player/sample-2.html") as response:
            assert 'src="/recordings/sample.wav"' in response.read().decode()


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
    finally:
        stopped = stop_viewer()

    assert stopped.running is False
