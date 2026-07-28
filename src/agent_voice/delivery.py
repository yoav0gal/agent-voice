from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .media import CONTENT_TYPES
from .viewer import (
    ensure_viewer,
    publish_recording,
    publish_player,
    recording_urls,
)


@dataclass(frozen=True)
class Delivery:
    browser_url: str | None = None
    audio_url: str | None = None
    recording_path: Path | None = None
    warning: str | None = None


def prepare_delivery(
    recording: Path,
    text: str,
    *,
    audio_format: str | None = None,
    recordings_dir: Path | None = None,
) -> Delivery:
    """Publish one recording to the lightweight local viewer."""
    path = recording.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Recording not found: {path}")
    if not isinstance(text, str):
        raise ValueError("Recording text must be a string")

    resolved_format = (audio_format or path.suffix.lstrip(".")).lower()
    if resolved_format not in CONTENT_TYPES:
        raise ValueError(f"Unsupported recording format: {resolved_format or '(none)'}")

    try:
        published = publish_recording(path, resolved_format, recordings_dir)
        player_name = publish_player(published, text)
        viewer = ensure_viewer(published.parent)
        browser_url, audio_url = recording_urls(viewer, published, player_name)
    except (OSError, RuntimeError) as error:
        return Delivery(
            warning=f"Could not start recording viewer; using file fallback ({error})",
        )

    return Delivery(
        browser_url=browser_url,
        audio_url=audio_url,
        recording_path=published,
    )
