from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .paths import project_root

DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
DEFAULT_FORMAT = "mp3"
DEFAULT_SERVICE_TIMEOUT_MINUTES = 10.0
MIN_SPEED = 0.5
MAX_SPEED = 4.0
FORMATS = ("wav", "mp3", "opus", "m4a")
_UNSET = object()


@dataclass(frozen=True)
class SpeechDefaults:
    voice: str = DEFAULT_VOICE
    speed: float = DEFAULT_SPEED
    format: str = DEFAULT_FORMAT
    service_timeout_minutes: float = DEFAULT_SERVICE_TIMEOUT_MINUTES
    output_dir: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "voice": self.voice,
            "speed": self.speed,
            "format": self.format,
            "service": {"timeout_minutes": self.service_timeout_minutes},
            "output_dir": self.output_dir,
        }


def config_path() -> Path:
    return project_root() / "config.json"


def load_defaults() -> SpeechDefaults:
    path = config_path()
    if not path.is_file():
        return SpeechDefaults()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Could not read Agent Voice config at {path}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise ValueError(f"Agent Voice config at {path} must be a JSON object")
    return _validated_defaults(
        payload.get("voice", DEFAULT_VOICE),
        payload.get("speed", DEFAULT_SPEED),
        payload.get("format", DEFAULT_FORMAT),
        _service_timeout(payload),
        payload.get("output_dir"),
    )


def update_defaults(
    *,
    voice: str | None = None,
    speed: float | None = None,
    format: str | None = None,
    service_timeout_minutes: float | None = None,
    output_dir: str | os.PathLike[str] | None | object = _UNSET,
) -> SpeechDefaults:
    current = load_defaults()
    updated = _validated_defaults(
        current.voice if voice is None else voice,
        current.speed if speed is None else speed,
        current.format if format is None else format,
        current.service_timeout_minutes
        if service_timeout_minutes is None
        else service_timeout_minutes,
        current.output_dir if output_dir is _UNSET else output_dir,
    )
    _write_config(updated)
    return updated


def reset_defaults() -> SpeechDefaults:
    config_path().unlink(missing_ok=True)
    return SpeechDefaults()


def _validated_defaults(
    voice: object,
    speed: object,
    format: object,
    service_timeout_minutes: object,
    output_dir: object,
) -> SpeechDefaults:
    if not isinstance(voice, str) or not voice.strip():
        raise ValueError("Default voice must be a non-empty string")
    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        raise ValueError("Default speed must be a number")
    value = float(speed)
    if not MIN_SPEED <= value <= MAX_SPEED:
        raise ValueError(f"Default speed must be between {MIN_SPEED} and {MAX_SPEED}")
    if not isinstance(format, str) or format.lower() not in FORMATS:
        raise ValueError(f"Default format must be one of: {', '.join(FORMATS)}")
    audio_format = format.lower()
    if isinstance(service_timeout_minutes, bool) or not isinstance(
        service_timeout_minutes, (int, float)
    ):
        raise ValueError("Service timeout must be a number of minutes")
    timeout = float(service_timeout_minutes)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Service timeout must be a finite number greater than zero")
    if output_dir is None:
        configured_output_dir = None
    else:
        if not isinstance(output_dir, (str, os.PathLike)):
            raise ValueError("Output directory must be a path or default")
        raw_output_dir = os.fspath(output_dir)
        if not raw_output_dir.strip():
            raise ValueError("Output directory must not be empty")
        path = Path(raw_output_dir).expanduser().resolve()
        if path.exists() and not path.is_dir():
            raise ValueError(f"Output directory is not a directory: {path}")
        configured_output_dir = str(path)
    return SpeechDefaults(
        voice.strip(),
        value,
        audio_format,
        timeout,
        configured_output_dir,
    )


def _service_timeout(payload: dict[str, object]) -> object:
    service = payload.get("service")
    if service is None:
        return payload.get("service_timeout_minutes", DEFAULT_SERVICE_TIMEOUT_MINUTES)
    if isinstance(service, str):
        return payload.get("service_timeout_minutes", DEFAULT_SERVICE_TIMEOUT_MINUTES)
    if not isinstance(service, dict):
        raise ValueError("Default service must be a JSON object")
    return service.get("timeout_minutes", DEFAULT_SERVICE_TIMEOUT_MINUTES)


def _write_config(defaults: SpeechDefaults) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".config.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(defaults.to_dict(), output, indent=2)
            output.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
