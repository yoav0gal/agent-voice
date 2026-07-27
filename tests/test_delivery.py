import os
import shlex
import subprocess

from agent_voice import delivery


def test_prepare_delivery_returns_portable_fallback_without_writes(tmp_path):
    recording = tmp_path / "Daily update & notes.mp3"
    recording.write_bytes(b"audio")

    result = delivery.prepare_delivery(recording)

    assert set(result) == {"fallback_markdown"}
    lines = result["fallback_markdown"].splitlines()
    assert lines[:3] == [
        "Agent Voice recording Daily update & notes.mp3",
        f"Listen: [media]({recording.as_uri()})",
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
    assert set(tmp_path.iterdir()) == {recording}
