from __future__ import annotations

import wave

import numpy as np
import pytest

from kokoro_cli import audio as audio_module
from kokoro_cli.audio import change_tempo, write_audio, write_audio_bytes


def test_write_wav(tmp_path):
    samples = np.array([-2.0, -0.5, 0.0, 0.5, 2.0], dtype=np.float32)
    output = write_audio(samples, 24_000, tmp_path / "test.wav", "wav")

    with wave.open(str(output), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 24_000
        assert audio.getnframes() == len(samples)


def test_output_format_is_validated(tmp_path):
    samples = np.zeros(4, dtype=np.float32)
    try:
        write_audio(samples, 24_000, tmp_path / "test.xyz", "xyz")
    except ValueError as error:
        assert "Unsupported format" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_failed_encode_preserves_existing_output(tmp_path, monkeypatch):
    output = tmp_path / "important.mp3"
    output.write_bytes(b"original")

    def fail_encode(*args, **kwargs):
        raise RuntimeError("encoder failed")

    monkeypatch.setattr(audio_module, "_encode_audio", fail_encode)
    with pytest.raises(RuntimeError, match="encoder failed"):
        write_audio(np.zeros(4, dtype=np.float32), 24_000, output, "mp3")

    assert output.read_bytes() == b"original"


def test_extensionless_compressed_output(tmp_path):
    output = write_audio(
        np.zeros(2_400, dtype=np.float32), 24_000, tmp_path / "recording", "mp3"
    )
    assert output.name == "recording"
    assert output.stat().st_size > 0


def test_empty_service_audio_does_not_overwrite_existing_output(tmp_path):
    output = tmp_path / "important.wav"
    output.write_bytes(b"original")

    with pytest.raises(RuntimeError, match="empty audio"):
        write_audio_bytes(b"", output)

    assert output.read_bytes() == b"original"


def test_change_tempo_uses_pitch_preserving_ffmpeg_filter(monkeypatch):
    samples = np.arange(8, dtype=np.float32)
    commands = []

    class Completed:
        stdout = np.arange(4, dtype="<f4").tobytes()

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(audio_module.shutil, "which", lambda name: "/bin/ffmpeg")
    monkeypatch.setattr(audio_module.subprocess, "run", run)

    changed = change_tempo(samples, 24_000, 2.0)

    assert len(changed) == 4
    command, kwargs = commands[0]
    assert "atempo=2.0" in command
    assert kwargs["input"] == samples.astype("<f4").tobytes()
