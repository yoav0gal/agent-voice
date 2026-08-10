from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .media import CONTENT_TYPES
from .viewer import (
    ensure_viewer,
    publish_control,
    publish_language,
    publish_recording,
    publish_player,
    publish_source,
    recording_control_urls,
    recording_urls,
)


@dataclass(frozen=True)
class Delivery:
    browser_url: str | None = None
    audio_url: str | None = None
    recording_path: Path | None = None
    controls: dict[str, str] | None = None
    warning: str | None = None


def prepare_delivery(
    recording: Path,
    text: str,
    *,
    source_text: str | None = None,
    language: str = "en-us",
    audio_format: str | None = None,
    recordings_dir: Path | None = None,
    controls: bool = False,
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
        source = text if source_text is None else source_text
        publish_source(path, source)
        if published != path:
            publish_source(published, source)
        player_name = publish_player(published, text)
        publish_language(published, language)
        viewer = ensure_viewer(published.parent)
        browser_url, audio_url = recording_urls(viewer, published, player_name)
    except (OSError, RuntimeError) as error:
        return Delivery(
            warning=f"Could not start recording viewer; using file fallback ({error})",
        )

    control_urls = None
    warning = None
    if controls:
        try:
            control_urls = recording_control_urls(publish_control(published))
        except (OSError, RuntimeError, ValueError) as error:
            warning = (
                f"Could not prepare playback controls; using viewer fallback ({error})"
            )

    return Delivery(
        browser_url=browser_url,
        audio_url=audio_url,
        recording_path=published,
        controls=control_urls,
        warning=warning,
    )
