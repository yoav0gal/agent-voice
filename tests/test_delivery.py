import os
import re
import shlex
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_voice import delivery


def test_prepare_delivery_creates_escaped_local_player_and_fallback(tmp_path):
    recording = tmp_path / "Daily update & notes.mp3"
    recording.write_bytes(b"audio")

    result = delivery.prepare_delivery(
        recording,
        'Visible <script>alert("no")</script> text.',
    )

    player = recording.with_suffix(".html")
    document = player.read_text()
    assert result.warning is None
    assert "<audio controls preload=\"metadata\">" in document
    assert 'src="Daily%20update%20%26%20notes.mp3"' in document
    assert 'type="audio/mpeg"' in document
    assert "&lt;script&gt;" in document
    assert "<script>" not in document
    assert "base64" not in document
    lines = result.fallback_markdown.splitlines()
    assert lines[:3] == [
        "Agent Voice recording Daily update & notes.mp3",
        f"Listen: [browser]({player.as_uri()}) · [media]({recording.as_uri()})",
        "```sh",
    ]
    assert lines[-1] == "```"
    if os.name == "nt":
        assert lines[3] == (
            f"agent-voice play {subprocess.list2cmdline([str(recording.resolve())])}"
        )
    else:
        assert shlex.split(lines[3]) == [
            "agent-voice",
            "play",
            str(recording.resolve()),
        ]


def test_prepare_delivery_preserves_existing_player_name(tmp_path):
    recording = tmp_path / "report.mp3"
    recording.write_bytes(b"audio")
    existing = recording.with_suffix(".html")
    existing.write_text("user-owned html")

    result = delivery.prepare_delivery(recording, "Visible text.")

    generated = tmp_path / "report-2.html"
    assert existing.read_text() == "user-owned html"
    assert generated.is_file()
    assert f"[browser]({generated.as_uri()})" in result.fallback_markdown


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_prepare_delivery_writes_private_player(tmp_path):
    recording = tmp_path / "private.mp3"
    recording.write_bytes(b"audio")

    delivery.prepare_delivery(recording, "Private response.")

    mode = stat.S_IMODE(recording.with_suffix(".html").stat().st_mode)
    assert mode == 0o600


def test_prepare_delivery_reserves_unique_players_concurrently(tmp_path):
    recording = tmp_path / "concurrent.mp3"
    recording.write_bytes(b"audio")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda index: delivery.prepare_delivery(recording, f"Text {index}"),
                range(8),
            )
        )

    players = sorted(tmp_path.glob("concurrent*.html"))
    assert len(players) == 8
    assert len({result.fallback_markdown for result in results}) == 8
    assert all("<audio controls" in player.read_text() for player in players)


def test_prepare_delivery_failure_keeps_audio_and_uses_media_fallback(
    tmp_path, monkeypatch
):
    recording = tmp_path / "fallback.mp3"
    recording.write_bytes(b"audio")

    def fail_template():
        raise OSError("template unavailable")

    monkeypatch.setattr(delivery, "_player_template", fail_template)

    result = delivery.prepare_delivery(recording, "Visible text.")

    assert recording.read_bytes() == b"audio"
    assert result.warning == (
        "Could not create HTML player; using media fallback "
        "(template unavailable)"
    )
    assert "[browser]" not in result.fallback_markdown
    assert f"Listen: [media]({recording.as_uri()})" in result.fallback_markdown
    assert not list(tmp_path.glob("*.html"))
    assert not list(tmp_path.glob("*.tmp"))


def test_prepare_delivery_uses_explicit_format_for_extensionless_output(tmp_path):
    recording = tmp_path / "recording"
    recording.write_bytes(b"audio")

    result = delivery.prepare_delivery(
        recording,
        "Visible text.",
        audio_format="opus",
    )

    document = recording.with_suffix(".html").read_text()
    assert 'type="audio/ogg"' in document
    assert re.search(r"\[browser\]\(file:.*recording\.html\)", result.fallback_markdown)


def test_prepare_delivery_rejects_unknown_audio_format(tmp_path):
    recording = tmp_path / "recording.flac"
    recording.write_bytes(b"audio")

    with pytest.raises(ValueError, match="Unsupported recording format"):
        delivery.prepare_delivery(recording, "Visible text.")
