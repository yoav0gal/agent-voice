from __future__ import annotations

from pathlib import Path

import pytest

from agent_voice import delivery
from agent_voice.viewer import Viewer


def _viewer(root: Path) -> Viewer:
    return Viewer(root.resolve(), 49123, 123)


def test_prepare_delivery_uses_http_player_audio_and_file_links(tmp_path, monkeypatch):
    recording = tmp_path / "Daily update & notes.mp3"
    recording.write_bytes(b"audio")
    monkeypatch.setattr(delivery, "ensure_viewer", _viewer)

    result = delivery.prepare_delivery(
        recording,
        "Visible response text.",
        recordings_dir=tmp_path,
    )

    assert result.warning is None
    assert result.recording_path == recording
    assert result.browser_url == (
        "http://127.0.0.1:49123/player/Daily%20update%20%26%20notes.html"
    )
    assert result.audio_url == (
        "http://127.0.0.1:49123/recordings/Daily%20update%20%26%20notes.mp3"
    )
    assert list(tmp_path.glob("*.html")) == []


def test_prepare_delivery_copies_external_output_and_stores_transcript(
    tmp_path, monkeypatch
):
    output = tmp_path / "export" / "report.m4a"
    output.parent.mkdir()
    output.write_bytes(b"m4a-audio")
    managed = tmp_path / "managed recordings"
    monkeypatch.setattr(delivery, "ensure_viewer", _viewer)

    result = delivery.prepare_delivery(
        output,
        "Visible response text.",
        audio_format="m4a",
        recordings_dir=managed,
    )

    assert result.recording_path == managed / "report.m4a"
    assert result.recording_path.read_bytes() == b"m4a-audio"
    assert {path.name for path in managed.iterdir()} == {
        "report.m4a",
        ".agent-voice-viewer",
    }
    assert result.audio_url.endswith("/recordings/report.m4a")
    assert output.read_bytes() == b"m4a-audio"


def test_prepare_delivery_adds_real_format_to_extensionless_output(
    tmp_path, monkeypatch
):
    output = tmp_path / "recording"
    output.write_bytes(b"opus-audio")
    managed = tmp_path / "managed"
    monkeypatch.setattr(delivery, "ensure_viewer", _viewer)

    result = delivery.prepare_delivery(
        output,
        "Visible response text.",
        audio_format="opus",
        recordings_dir=managed,
    )

    assert result.recording_path == managed / "recording.opus"
    assert result.audio_url.endswith("/recordings/recording.opus")


def test_prepare_delivery_preserves_existing_managed_recording(tmp_path, monkeypatch):
    output = tmp_path / "report.mp3"
    output.write_bytes(b"existing")
    external = tmp_path / "external" / "report.mp3"
    external.parent.mkdir()
    external.write_bytes(b"new")
    monkeypatch.setattr(delivery, "ensure_viewer", _viewer)

    result = delivery.prepare_delivery(
        external,
        "Visible response text.",
        recordings_dir=tmp_path,
    )

    assert output.read_bytes() == b"existing"
    assert result.recording_path == tmp_path / "report-2.mp3"
    assert result.recording_path.read_bytes() == b"new"


def test_viewer_failure_keeps_audio_and_uses_file_fallback(tmp_path, monkeypatch):
    recording = tmp_path / "fallback.mp3"
    recording.write_bytes(b"audio")
    monkeypatch.setattr(
        delivery,
        "ensure_viewer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("not available")),
    )

    result = delivery.prepare_delivery(
        recording,
        "Visible response text.",
        recordings_dir=tmp_path,
    )

    assert recording.read_bytes() == b"audio"
    assert result.warning == (
        "Could not start recording viewer; using file fallback (not available)"
    )
    assert result.browser_url is None
    assert result.audio_url is None
    assert result.recording_path is None


def test_prepare_delivery_rejects_unknown_audio_format(tmp_path):
    recording = tmp_path / "recording.flac"
    recording.write_bytes(b"audio")

    with pytest.raises(ValueError, match="Unsupported recording format"):
        delivery.prepare_delivery(recording, "Visible response text.")
