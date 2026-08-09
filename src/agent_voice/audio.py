from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import wave
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
import miniaudio
import numpy as np
from numpy.typing import NDArray

from .config import FORMATS, MAX_SPEED, MIN_SPEED

PLAYBACK_SAMPLE_RATE = 24_000
PLAYBACK_CHANNELS = 1
PLAYBACK_SAMPLE_WIDTH = 2
PLAYBACK_SEEK_SECONDS = 10
PLAYBACK_SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
PLAYBACK_ACTIONS = ("toggle", "restart", "back", "forward", "slower", "faster")


@dataclass(frozen=True)
class AudioRuntime:
    ffmpeg_path: str | None
    ffmpeg_version: str | None
    ffmpeg_error: str | None
    miniaudio_version: str
    playback_backend: str | None
    playback_error: str | None


@dataclass(frozen=True)
class PlaybackState:
    recording: str
    playing: bool
    position_seconds: float
    speed: float

    def to_dict(self) -> dict[str, object]:
        return {
            "recording": self.recording,
            "playing": self.playing,
            "position_seconds": round(self.position_seconds, 3),
            "speed": self.speed,
        }


class PlaybackController:
    """Control one nonblocking local playback session."""

    def __init__(
        self,
        *,
        decoder: Callable[[Path], bytes] = lambda path: _decode_for_playback(path),
        device_factory: Callable[
            ..., miniaudio.PlaybackDevice
        ] = miniaudio.PlaybackDevice,
        tempo_changer: Callable[[bytes, float], bytes] = lambda pcm, factor: (
            _change_pcm_tempo(pcm, factor)
        ),
    ) -> None:
        self._decoder = decoder
        self._device_factory = device_factory
        self._tempo_changer = tempo_changer
        self._command_lock = threading.Lock()
        self._lock = threading.Lock()
        self._recording: Path | None = None
        self._source_pcm = b""
        self._pcm = b""
        self._offset = 0
        self._speed = 1.0
        self._playing = False
        self._closed = False
        self._silence = b""
        self._device: miniaudio.PlaybackDevice | None = None
        self._stream: Generator[bytes | memoryview, int, None] | None = None

    def control(self, recording: Path, action: str) -> PlaybackState:
        if action not in PLAYBACK_ACTIONS:
            raise ValueError(f"Unsupported playback action: {action}")

        path = recording.expanduser().resolve()
        with self._command_lock:
            if self._closed:
                raise RuntimeError("Playback controller is closed")
            with self._lock:
                changed = self._recording != path
            if changed:
                pcm = self._decoder(path)
                with self._lock:
                    self._recording = path
                    self._source_pcm = pcm
                    self._pcm = pcm
                    self._offset = 0
                    self._speed = 1.0
                    self._playing = False

            if action in ("slower", "faster"):
                with self._lock:
                    index = PLAYBACK_SPEEDS.index(self._speed)
                    step = -1 if action == "slower" else 1
                    speed = PLAYBACK_SPEEDS[
                        min(max(0, index + step), len(PLAYBACK_SPEEDS) - 1)
                    ]
                    source_pcm = self._source_pcm
                    current_speed = self._speed
                if speed != current_speed:
                    # ponytail: rebuild one full PCM buffer per speed click; cache
                    # variants only if real recordings make latency or memory hurt.
                    pcm = self._tempo_changer(source_pcm, speed)
                    with self._lock:
                        source_offset = self._source_offset()
                        self._pcm = pcm
                        self._speed = speed
                        self._offset = self._playback_offset(source_offset)
                        if self._offset >= len(self._pcm):
                            self._playing = False

            with self._lock:
                if action == "toggle":
                    if self._offset >= len(self._pcm):
                        self._offset = 0
                    self._playing = True if changed else not self._playing
                elif action == "restart":
                    self._offset = 0
                    self._playing = True
                elif action in ("back", "forward"):
                    seconds = (
                        -PLAYBACK_SEEK_SECONDS
                        if action == "back"
                        else PLAYBACK_SEEK_SECONDS
                    )
                    delta = seconds * PLAYBACK_SAMPLE_RATE * PLAYBACK_SAMPLE_WIDTH
                    source_offset = min(
                        max(0, self._source_offset() + delta), len(self._source_pcm)
                    )
                    self._offset = self._playback_offset(source_offset)
                    if source_offset >= len(self._source_pcm):
                        self._playing = False
                playing = self._playing
            try:
                self._sync_device(playing)
            except BaseException:
                with self._lock:
                    self._recording = None
                    self._source_pcm = b""
                    self._pcm = b""
                    self._offset = 0
                    self._speed = 1.0
                    self._playing = False
                raise
            with self._lock:
                return self._state()

    def close(self) -> None:
        with self._command_lock:
            self._closed = True
            with self._lock:
                self._playing = False
            self._discard_device()

    def _sync_device(self, playing: bool) -> None:
        try:
            if playing:
                self._start_device()
                return
            if self._device is not None and self._device.running:
                self._device.stop()
        except miniaudio.MiniaudioError as error:
            self._discard_device()
            raise RuntimeError(f"audio playback failed: {error}") from error

    def _start_device(self) -> None:
        if self._device is not None:
            if not self._device.running and self._stream is not None:
                self._device.start(self._stream)
            return
        stream = self._chunks()
        next(stream)
        device = self._device_factory(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=PLAYBACK_CHANNELS,
            sample_rate=PLAYBACK_SAMPLE_RATE,
            app_name="Agent Voice",
        )
        try:
            device.start(stream)
        except BaseException:
            stream.close()
            try:
                device.close()
            except miniaudio.MiniaudioError:
                pass
            raise
        self._stream = stream
        self._device = device

    def _discard_device(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            except miniaudio.MiniaudioError:
                pass
            self._device = None
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def _chunks(self) -> Generator[bytes | memoryview, int, None]:
        frame_width = PLAYBACK_CHANNELS * PLAYBACK_SAMPLE_WIDTH
        required_frames = yield b""
        while True:
            requested_bytes = (required_frames or 4096) * frame_width
            with self._lock:
                if self._playing and self._offset < len(self._pcm):
                    start = self._offset
                    self._offset = min(start + requested_bytes, len(self._pcm))
                    chunk: bytes | memoryview = memoryview(self._pcm)[
                        start : self._offset
                    ]
                    if self._offset >= len(self._pcm):
                        # ponytail: completion feeds silence; add an idle monitor if
                        # holding the audio device becomes a real resource problem.
                        self._playing = False
                else:
                    if len(self._silence) < requested_bytes:
                        self._silence = bytes(requested_bytes)
                    chunk = memoryview(self._silence)[:requested_bytes]
            required_frames = yield chunk

    def _state(self) -> PlaybackState:
        if self._recording is None:
            raise RuntimeError("No recording is loaded")
        bytes_per_second = (
            PLAYBACK_SAMPLE_RATE * PLAYBACK_CHANNELS * PLAYBACK_SAMPLE_WIDTH
        )
        return PlaybackState(
            recording=self._recording.name,
            playing=self._playing,
            position_seconds=self._source_offset() / bytes_per_second,
            speed=self._speed,
        )

    def _source_offset(self) -> int:
        if self._offset >= len(self._pcm):
            return len(self._source_pcm)
        return min(int(self._offset * self._speed), len(self._source_pcm))

    def _playback_offset(self, source_offset: int) -> int:
        if source_offset >= len(self._source_pcm):
            frame_width = PLAYBACK_CHANNELS * PLAYBACK_SAMPLE_WIDTH
            return len(self._pcm) - len(self._pcm) % frame_width
        frame_width = PLAYBACK_CHANNELS * PLAYBACK_SAMPLE_WIDTH
        offset = int(source_offset / self._speed)
        return min(offset - offset % frame_width, len(self._pcm))


def inspect_audio_runtime() -> AudioRuntime:
    """Inspect the bundled codec and native playback runtimes."""
    try:
        ffmpeg_path = _ffmpeg_executable()
        ffmpeg_version = imageio_ffmpeg.get_ffmpeg_version()
        ffmpeg_error = None
    except RuntimeError as error:
        ffmpeg_path = None
        ffmpeg_version = None
        ffmpeg_error = str(error)

    try:
        with miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=PLAYBACK_CHANNELS,
            sample_rate=PLAYBACK_SAMPLE_RATE,
            app_name="Agent Voice",
        ) as device:
            playback_backend = device.backend
        playback_error = None
    except miniaudio.MiniaudioError as error:
        playback_backend = None
        playback_error = str(error)

    return AudioRuntime(
        ffmpeg_path=ffmpeg_path,
        ffmpeg_version=ffmpeg_version,
        ffmpeg_error=ffmpeg_error,
        miniaudio_version=miniaudio.__version__,
        playback_backend=playback_backend,
        playback_error=playback_error,
    )


def change_tempo(
    samples: NDArray[np.floating], sample_rate: int, factor: float
) -> NDArray[np.float32]:
    """Change speech tempo with bundled FFmpeg while preserving pitch."""
    if factor == 1.0:
        return np.asarray(samples, dtype=np.float32).reshape(-1)
    if not MIN_SPEED <= factor <= MAX_SPEED:
        raise ValueError(f"Tempo factor must be between {MIN_SPEED} and {MAX_SPEED}")

    source = np.asarray(samples, dtype="<f4").reshape(-1)
    tempo_filter = ",".join(
        f"atempo={tempo_factor}" for tempo_factor in _tempo_factors(factor)
    )
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "f32le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-i",
        "pipe:0",
        "-filter:a",
        tempo_filter,
        "-f",
        "f32le",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command, input=source.tobytes(), check=True, capture_output=True
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"ffmpeg could not change speech tempo: {detail}") from error
    return np.frombuffer(completed.stdout, dtype="<f4").copy()


def _change_pcm_tempo(pcm: bytes, factor: float) -> bytes:
    if factor == 1.0:
        return pcm
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32_768
    changed = change_tempo(samples, PLAYBACK_SAMPLE_RATE, factor)
    return np.clip(np.rint(changed * 32_768), -32_768, 32_767).astype("<i2").tobytes()


def _tempo_factors(factor: float) -> list[float]:
    """Split aggressive speedups into pitch-preserving FFmpeg tempo stages."""
    factors: list[float] = []
    remaining = float(factor)
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    factors.append(remaining)
    return factors


def write_audio(
    samples: NDArray[np.floating],
    sample_rate: int,
    destination: Path,
    audio_format: str,
) -> Path:
    audio_format = audio_format.lower()
    if audio_format not in FORMATS:
        raise ValueError(
            f"Unsupported format '{audio_format}'. Choose: {', '.join(FORMATS)}"
        )

    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=f".{audio_format}",
        dir=destination.parent,
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        if audio_format == "wav":
            _write_wav(samples, sample_rate, temporary)
        else:
            _encode_audio(samples, sample_rate, temporary, audio_format)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def write_audio_bytes(data: bytes, destination: Path) -> Path:
    """Atomically persist audio returned by the localhost service."""
    if not data:
        raise RuntimeError("The Agent Voice service returned an empty audio response")
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def play_audio(path: Path) -> None:
    """Decode a recording with bundled FFmpeg and play it through miniaudio."""
    pcm = _decode_for_playback(path)
    _play_pcm(pcm)


def _encode_audio(
    samples: NDArray[np.floating],
    sample_rate: int,
    destination: Path,
    audio_format: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="agent-voice-") as directory:
        source = Path(directory) / "source.wav"
        _write_wav(samples, sample_rate, source)
        command = [
            _ffmpeg_executable(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
        ]
        if audio_format == "mp3":
            command += ["-codec:a", "libmp3lame", "-q:a", "3"]
        elif audio_format == "opus":
            command += ["-codec:a", "libopus", "-b:a", "48k"]
        else:
            command += ["-codec:a", "aac", "-b:a", "128k"]
        command.append(str(destination))
        try:
            subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"ffmpeg could not create {audio_format}: {detail}"
            ) from error


def _ffmpeg_executable() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError as error:
        raise RuntimeError(
            "Bundled FFmpeg is unavailable; reinstall Agent Voice"
        ) from error


def _decode_for_playback(path: Path) -> bytes:
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(PLAYBACK_SAMPLE_RATE),
        "-ac",
        str(PLAYBACK_CHANNELS),
        "pipe:1",
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            f"ffmpeg could not decode audio for playback: {detail}"
        ) from error
    if not completed.stdout:
        raise RuntimeError("ffmpeg returned empty audio for playback")
    return completed.stdout


def _play_pcm(pcm: bytes) -> None:
    finished = threading.Event()
    stream = _pcm_stream(pcm, finished)
    next(stream)
    try:
        with miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=PLAYBACK_CHANNELS,
            sample_rate=PLAYBACK_SAMPLE_RATE,
            app_name="Agent Voice",
        ) as device:
            device.start(stream)
            duration = len(pcm) / (
                PLAYBACK_SAMPLE_RATE * PLAYBACK_CHANNELS * PLAYBACK_SAMPLE_WIDTH
            )
            if not finished.wait(timeout=max(5.0, duration + 5.0)):
                raise RuntimeError("audio playback timed out")
    except miniaudio.MiniaudioError as error:
        raise RuntimeError(f"audio playback failed: {error}") from error
    finally:
        stream.close()


def _pcm_stream(
    pcm: bytes, finished: threading.Event
) -> Generator[bytes | memoryview, int, None]:
    offset = 0
    frame_width = PLAYBACK_CHANNELS * PLAYBACK_SAMPLE_WIDTH
    try:
        required_frames = yield b""
        while offset < len(pcm):
            requested_bytes = (required_frames or 4096) * frame_width
            end = min(offset + requested_bytes, len(pcm))
            required_frames = yield memoryview(pcm)[offset:end]
            offset = end
    finally:
        finished.set()


def _write_wav(samples: NDArray[np.floating], sample_rate: int, path: Path) -> None:
    normalized = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = (np.clip(normalized, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())
