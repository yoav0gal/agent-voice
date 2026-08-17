from __future__ import annotations

from importlib import resources


CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "m4a": "audio/mp4",
}


def generating_audio(audio_format: str) -> bytes:
    return (
        resources.files("agent_voice")
        .joinpath("resources", f"generating.{audio_format}")
        .read_bytes()
    )
