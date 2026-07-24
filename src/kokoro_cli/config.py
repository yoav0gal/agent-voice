from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import project_root

DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
MIN_SPEED = 0.5
MAX_SPEED = 4.0


@dataclass(frozen=True)
class SpeechDefaults:
    voice: str = DEFAULT_VOICE
    speed: float = DEFAULT_SPEED

    def to_dict(self) -> dict[str, str | float]:
        return asdict(self)


def config_path() -> Path:
    return project_root() / "config.json"


def load_defaults() -> SpeechDefaults:
    path = config_path()
    if not path.is_file():
        return SpeechDefaults()
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read Kokoro config at {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Kokoro config at {path} must be a JSON object")
    return _validated_defaults(
        payload.get("voice", DEFAULT_VOICE),
        payload.get("speed", DEFAULT_SPEED),
    )


def update_defaults(
    *, voice: str | None = None, speed: float | None = None
) -> SpeechDefaults:
    current = load_defaults()
    updated = _validated_defaults(
        current.voice if voice is None else voice,
        current.speed if speed is None else speed,
    )
    _write_config(updated)
    return updated


def reset_defaults() -> SpeechDefaults:
    config_path().unlink(missing_ok=True)
    return SpeechDefaults()


def _validated_defaults(voice: object, speed: object) -> SpeechDefaults:
    if not isinstance(voice, str) or not voice.strip():
        raise ValueError("Default voice must be a non-empty string")
    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        raise ValueError("Default speed must be a number")
    value = float(speed)
    if not MIN_SPEED <= value <= MAX_SPEED:
        raise ValueError(f"Default speed must be between {MIN_SPEED} and {MAX_SPEED}")
    return SpeechDefaults(voice.strip(), value)


def _write_config(defaults: SpeechDefaults) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".config.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(defaults.to_dict(), output, indent=2)
            output.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
