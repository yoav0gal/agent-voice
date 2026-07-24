from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

FORMATS = ("wav", "mp3", "opus", "m4a")
CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "m4a": "audio/mp4",
}


def change_tempo(
    samples: NDArray[np.floating], sample_rate: int, factor: float
) -> NDArray[np.float32]:
    """Change speech tempo with ffmpeg while preserving the original pitch."""
    if factor == 1.0:
        return np.asarray(samples, dtype=np.float32).reshape(-1)
    if not 0.5 <= factor <= 2.0:
        raise ValueError("Tempo factor must be between 0.5 and 2.0")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for speech speeds above 2.0")

    source = np.asarray(samples, dtype="<f4").reshape(-1)
    command = [
        ffmpeg,
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
        f"atempo={factor}",
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
        raise RuntimeError("The Kokoro service returned an empty audio response")
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
    afplay = shutil.which("afplay")
    ffplay = shutil.which("ffplay")
    players = [ffplay, afplay] if path.suffix.lower() == ".opus" else [afplay, ffplay]
    players = [player for player in players if player]
    if not players:
        raise RuntimeError("No audio player found (expected afplay or ffplay)")
    last_error: subprocess.CalledProcessError | None = None
    for player in players:
        command = [player, str(path)]
        player_name = Path(str(player).replace("\\", "/")).name.lower()
        if player_name in {"ffplay", "ffplay.exe"}:
            command[1:1] = ["-nodisp", "-autoexit", "-loglevel", "error"]
        try:
            subprocess.run(command, check=True, capture_output=True)
            return
        except subprocess.CalledProcessError as error:
            last_error = error
    raise RuntimeError(f"Audio playback failed: {last_error}")


def _encode_audio(
    samples: NDArray[np.floating],
    sample_rate: int,
    destination: Path,
    audio_format: str,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(f"ffmpeg is required to create {audio_format} files")

    with tempfile.TemporaryDirectory(prefix="kokoro-cli-") as directory:
        source = Path(directory) / "source.wav"
        _write_wav(samples, sample_rate, source)
        command = [
            ffmpeg,
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


def _write_wav(samples: NDArray[np.floating], sample_rate: int, path: Path) -> None:
    normalized = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = (np.clip(normalized, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())
