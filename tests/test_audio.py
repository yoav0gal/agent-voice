from __future__ import annotations

import wave

import numpy as np
import pytest

from agent_voice import audio as audio_module
from agent_voice.audio import change_tempo, write_audio, write_audio_bytes


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


@pytest.mark.parametrize(
    ("factor", "expected_filter"),
    [
        (0.5, "atempo=0.5"),
        (0.75, "atempo=0.75"),
        (1.5, "atempo=1.5"),
        (2.0, "atempo=2.0"),
        (3.0, "atempo=2.0,atempo=1.5"),
        (4.0, "atempo=2.0,atempo=2.0"),
    ],
)
def test_change_tempo_uses_pitch_preserving_ffmpeg_filter(
    monkeypatch, factor, expected_filter
):
    samples = np.arange(8, dtype=np.float32)
    commands = []

    class Completed:
        stdout = np.arange(4, dtype="<f4").tobytes()

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(audio_module, "_ffmpeg_executable", lambda: "/bundled/ffmpeg")
    monkeypatch.setattr(audio_module.subprocess, "run", run)

    changed = change_tempo(samples, 24_000, factor)

    assert len(changed) == 4
    command, kwargs = commands[0]
    assert command[command.index("-filter:a") + 1] == expected_filter
    assert kwargs["input"] == samples.astype("<f4").tobytes()


def test_change_tempo_at_natural_speed_does_not_require_ffmpeg(monkeypatch):
    samples = np.arange(8, dtype=np.float64)
    monkeypatch.setattr(
        audio_module,
        "_ffmpeg_executable",
        lambda: pytest.fail("FFmpeg lookup should not occur at 1.0x"),
    )

    changed = change_tempo(samples, 24_000, 1.0)

    assert changed.dtype == np.float32
    np.testing.assert_array_equal(changed, samples.astype(np.float32))


def test_ffmpeg_executable_uses_packaged_runtime(monkeypatch):
    monkeypatch.setattr(
        audio_module.imageio_ffmpeg,
        "get_ffmpeg_exe",
        lambda: "/package/imageio_ffmpeg/ffmpeg",
    )

    assert audio_module._ffmpeg_executable() == "/package/imageio_ffmpeg/ffmpeg"


@pytest.mark.parametrize("factor", [0.49, 4.01])
def test_change_tempo_rejects_unsupported_factor(factor):
    with pytest.raises(ValueError, match="between 0.5 and 4.0"):
        change_tempo(np.zeros(8, dtype=np.float32), 24_000, factor)


def test_play_audio_decodes_with_bundled_ffmpeg(tmp_path, monkeypatch):
    commands = []
    played = []

    class Completed:
        stdout = b"\x00\x00\x01\x00"

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(audio_module, "_ffmpeg_executable", lambda: "/bundled/ffmpeg")
    monkeypatch.setattr(audio_module.subprocess, "run", run)
    monkeypatch.setattr(audio_module, "_play_pcm", played.append)

    audio_module.play_audio(tmp_path / "recording.wav")

    command, kwargs = commands[0]
    assert command[0] == "/bundled/ffmpeg"
    assert command[command.index("-f") + 1] == "s16le"
    assert command[command.index("-ar") + 1] == "24000"
    assert kwargs == {"check": True, "capture_output": True}
    assert played == [b"\x00\x00\x01\x00"]


def test_play_pcm_uses_miniaudio_until_stream_finishes(monkeypatch):
    chunks = []
    device_options = {}
    closed = []

    class FakeDevice:
        def __init__(self, **kwargs):
            device_options.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(True)

        def start(self, stream):
            while True:
                try:
                    chunks.append(bytes(stream.send(2)))
                except StopIteration:
                    return

    monkeypatch.setattr(audio_module.miniaudio, "PlaybackDevice", FakeDevice)

    audio_module._play_pcm(b"\x00\x00\x01\x00\x02\x00")

    assert chunks == [b"\x00\x00\x01\x00", b"\x02\x00"]
    assert device_options["nchannels"] == 1
    assert device_options["sample_rate"] == 24_000
    assert device_options["app_name"] == "Agent Voice"
    assert closed == [True]
