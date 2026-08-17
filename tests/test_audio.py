from __future__ import annotations

import threading
import time
import wave
from types import SimpleNamespace

import miniaudio
import numpy as np
import pytest

from agent_voice import audio as audio_module
from agent_voice.audio import (
    PlaybackController,
    change_tempo,
    write_audio,
    write_audio_bytes,
)
from agent_voice.paths import pending_generation_path, streaming_pcm_path


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


def test_windows_ffmpeg_processes_do_not_open_console_windows(monkeypatch):
    monkeypatch.setattr(audio_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        audio_module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False
    )

    assert audio_module._no_window_creation_flags() == 0x08000000


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
    monkeypatch.setattr(audio_module, "_no_window_creation_flags", lambda: 123)
    monkeypatch.setattr(audio_module.subprocess, "run", run)
    monkeypatch.setattr(audio_module, "_play_pcm", played.append)

    audio_module.play_audio(tmp_path / "recording.wav")

    command, kwargs = commands[0]
    assert command[0] == "/bundled/ffmpeg"
    assert command[command.index("-f") + 1] == "s16le"
    assert command[command.index("-ar") + 1] == "24000"
    assert kwargs == {"check": True, "capture_output": True, "creationflags": 123}
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


def test_playback_controller_toggle_pauses_and_resumes_without_redecoding(tmp_path):
    recording = tmp_path / "sample.mp3"
    recording.write_bytes(b"audio")
    decodes = []
    devices = []

    class Device:
        def __init__(self):
            devices.append(self)
            self.running = False

        def start(self, stream):
            self.stream = stream
            self.running = True

        def stop(self):
            self.running = False

        def close(self):
            self.running = False

    controller = PlaybackController(
        decoder=lambda path: decodes.append(path) or bytes(96_000),
        device_factory=lambda **_options: Device(),
    )
    try:
        assert controller.control(recording, "toggle").playing is True
        devices[0].stream.send(24_000)
        assert controller.control(recording, "toggle").playing is False
        resumed = controller.control(recording, "toggle")
        assert resumed.playing is True
        assert resumed.position_seconds == 1.0
    finally:
        controller.close()

    assert decodes == [recording.resolve()]


def test_playback_controller_restarts_and_seeks_ten_seconds(tmp_path):
    recording = tmp_path / "sample.mp3"
    recording.write_bytes(b"audio")
    controller = PlaybackController(
        decoder=lambda _path: bytes(30 * 48_000),
        device_factory=lambda **_options: SimpleNamespace(
            start=lambda _stream: None,
            close=lambda: None,
        ),
    )
    try:
        assert controller.control(recording, "forward").position_seconds == 10
        assert controller.control(recording, "forward").position_seconds == 20
        end = controller.control(recording, "forward")
        assert end.position_seconds == 30
        assert end.playing is False
        assert controller.control(recording, "back").position_seconds == 20
        restarted = controller.control(recording, "restart")
        assert restarted.position_seconds == 0
        assert restarted.playing is True
    finally:
        controller.close()


def test_playback_controller_forward_waits_for_full_ten_seconds(tmp_path):
    recording = tmp_path / "sample.mp3"
    recording.write_bytes(b"audio")
    controller = PlaybackController(decoder=lambda _path: bytes(15 * 48_000))
    try:
        assert controller.control(recording, "forward").position_seconds == 10
        assert controller.control(recording, "forward").position_seconds == 10
    finally:
        controller.close()


def test_playback_controller_forward_clamps_to_live_edge(tmp_path):
    recording = tmp_path / "sample.mp3"
    recording.touch()
    pending_generation_path(recording).touch()
    stream = streaming_pcm_path(recording)
    stream.write_bytes(bytes(15 * 48_000))
    controller = PlaybackController()
    try:
        controller.control(recording, "forward")
        deadline = time.monotonic() + 1
        while len(controller._source_pcm) < stream.stat().st_size:
            assert time.monotonic() < deadline
            time.sleep(0.01)

        controller.control(recording, "back")
        assert controller.control(recording, "forward").position_seconds == 10
        assert controller.control(recording, "forward").position_seconds == 15
    finally:
        controller.close()


def test_playback_controller_plays_pcm_as_it_is_generated(tmp_path):
    recording = tmp_path / "sample.mp3"
    recording.touch()
    pending_generation_path(recording).touch()
    streaming_pcm_path(recording).touch()
    device = SimpleNamespace(running=False)

    def start(stream):
        device.stream = stream
        device.running = True

    device.start = start
    device.stop = lambda: setattr(device, "running", False)
    device.close = device.stop
    processed = threading.Event()

    def change_tempo(pcm, _speed):
        processed.set()
        return pcm

    controller = PlaybackController(
        device_factory=lambda **_options: device,
        tempo_changer=change_tempo,
    )
    try:
        assert controller.control(recording, "toggle").playing is True
        faster = controller.control(recording, "faster")
        assert faster.speed == 1.25
        assert faster.playing is True
        assert bytes(device.stream.send(2)) == bytes(4)

        streaming_pcm_path(recording).write_bytes(b"\x01\x00\x02\x00")
        assert processed.wait(timeout=1)
        assert bytes(device.stream.send(2)) == b"\x01\x00\x02\x00"
        paused = controller.control(recording, "toggle")
        assert paused.playing is False
        assert paused.position_seconds > 0
        resumed = controller.control(recording, "toggle")
        assert resumed.playing is True
        assert resumed.position_seconds == paused.position_seconds
        assert (
            controller.control(recording, "forward").position_seconds
            == resumed.position_seconds
        )

        recording.write_bytes(b"complete")
        pending_generation_path(recording).unlink()
        deadline = time.monotonic() + 1
        while controller._streaming_locked() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert bytes(device.stream.send(2)) == bytes(4)
        assert controller.control(recording, "toggle").playing is True
    finally:
        controller.close()


def test_playback_controller_reloads_after_live_generation_fails(tmp_path):
    recording = tmp_path / "sample.mp3"
    recording.touch()
    pending_generation_path(recording).touch()
    streaming_pcm_path(recording).write_bytes(b"\x01\x00")
    decoded = []

    def decode(path):
        decoded.append(path)
        return b"\x02\x00"

    controller = PlaybackController(decoder=decode)
    try:
        controller.control(recording, "forward")
        recording.unlink()
        pending_generation_path(recording).unlink()
        deadline = time.monotonic() + 1
        while controller._recording is not None and time.monotonic() < deadline:
            time.sleep(0.01)

        recording.write_bytes(b"regenerated")
        state = controller.control(recording, "forward")

        assert decoded == [recording.resolve()]
        assert state.playing is False
    finally:
        controller.close()


def test_playback_controller_changes_speed_from_half_to_double_at_same_position(
    tmp_path,
):
    recording = tmp_path / "sample.mp3"
    recording.write_bytes(b"audio")
    changes = []

    class Device:
        running = False

        def start(self, _stream):
            self.running = True

        def stop(self):
            self.running = False

        def close(self):
            self.running = False

    def change_tempo(pcm, speed):
        changes.append(speed)
        return bytes(int(len(pcm) / speed))

    controller = PlaybackController(
        decoder=lambda _path: bytes(60 * 48_000),
        device_factory=lambda **_options: Device(),
        tempo_changer=change_tempo,
    )
    try:
        assert controller.control(recording, "forward").position_seconds == 10
        assert controller.control(recording, "slower").speed == 0.75
        slowest = controller.control(recording, "slower")
        assert slowest.speed == 0.5
        assert slowest.position_seconds == 10
        assert controller.control(recording, "slower").speed == 0.5
        assert controller.control(recording, "forward").position_seconds == 20
        assert controller.control(recording, "back").position_seconds == 10

        for _ in range(6):
            fastest = controller.control(recording, "faster")
        assert fastest.speed == 2.0
        assert fastest.position_seconds == pytest.approx(10, abs=0.001)

        assert controller.control(recording, "toggle").playing is True
        changed_while_playing = controller.control(recording, "slower")
        assert changed_while_playing.speed == 1.75
        assert changed_while_playing.playing is True
        assert changed_while_playing.position_seconds == pytest.approx(10, abs=0.001)

        other = tmp_path / "other.mp3"
        other.write_bytes(b"audio")
        switched = controller.control(other, "faster")
        assert switched.speed == 1.25
        assert switched.position_seconds == 0
        assert switched.playing is False
    finally:
        controller.close()

    assert changes == [
        0.75,
        0.5,
        0.75,
        1.0,
        1.25,
        1.5,
        1.75,
        2.0,
        1.75,
        1.25,
    ]


def test_playback_controller_uses_live_position_after_tempo_change(tmp_path):
    recording = tmp_path / "sample.mp3"
    recording.write_bytes(b"audio")
    device = SimpleNamespace(running=False)

    def start(stream):
        device.stream = stream
        device.running = True

    device.start = start
    device.stop = lambda: setattr(device, "running", False)
    device.close = device.stop

    def change_tempo(pcm, speed):
        device.stream.send(24_000)
        return bytes(int(len(pcm) / speed))

    controller = PlaybackController(
        decoder=lambda _path: bytes(20 * 48_000),
        device_factory=lambda **_options: device,
        tempo_changer=change_tempo,
    )
    try:
        controller.control(recording, "toggle")
        device.stream.send(24_000)
        changed = controller.control(recording, "faster")
    finally:
        controller.close()

    assert changed.position_seconds == 2


def test_playback_controller_keeps_prior_speed_when_tempo_change_fails(tmp_path):
    recording = tmp_path / "sample.mp3"
    recording.write_bytes(b"audio")
    controller = PlaybackController(
        decoder=lambda _path: bytes(30 * 48_000),
        tempo_changer=lambda _pcm, _speed: (_ for _ in ()).throw(
            RuntimeError("tempo failed")
        ),
    )
    try:
        assert controller.control(recording, "forward").position_seconds == 10
        with pytest.raises(RuntimeError, match="tempo failed"):
            controller.control(recording, "faster")
        state = controller.control(recording, "back")
        assert state.speed == 1.0
        assert state.position_seconds == 0
        assert state.playing is False
    finally:
        controller.close()


def test_playback_controller_recovers_after_device_start_failure(tmp_path):
    recording = tmp_path / "sample.mp3"
    recording.write_bytes(b"audio")
    starts = []

    class Device:
        running = False

        def start(self, _stream):
            starts.append(None)
            if len(starts) == 1:
                raise miniaudio.MiniaudioError("failed")
            self.running = True

        def stop(self):
            self.running = False

        def close(self):
            self.running = False

    controller = PlaybackController(
        decoder=lambda _path: bytes(48_000),
        device_factory=lambda **_options: Device(),
    )
    try:
        with pytest.raises(RuntimeError, match="audio playback failed"):
            controller.control(recording, "toggle")
        assert controller.control(recording, "toggle").playing is True
    finally:
        controller.close()

    assert len(starts) == 2
