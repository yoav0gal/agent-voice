from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template

from .media import CONTENT_TYPES
from .viewer import (
    ensure_viewer,
    publish_recording,
    publish_transcript,
    recording_urls,
)


_FALLBACK_TEMPLATE_RESOURCE = ("templates", "fallback-response.md")


@dataclass(frozen=True)
class Delivery:
    fallback_markdown: str
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
        publish_transcript(published, text)
        viewer = ensure_viewer(published.parent)
        browser_url, audio_url = recording_urls(viewer, published)
    except (OSError, RuntimeError) as error:
        return Delivery(
            _local_fallback_markdown(path),
            warning=f"Could not start recording viewer; using file fallback ({error})",
        )

    return Delivery(
        _fallback_template().substitute(
            RECORDING_NAME=path.name,
            BROWSER_URL=browser_url,
            AUDIO_URL=audio_url,
            RECORDING_URL=path.as_uri(),
            PLAY_COMMAND=_terminal_command(path),
        ),
        browser_url,
        audio_url,
        published,
    )


def _local_fallback_markdown(path: Path) -> str:
    return (
        "---\n\n"
        f"Agent Voice recording {path.name}\n"
        f"Listen: [media app]({path.as_uri()})\n"
        "```sh\n"
        f"{_terminal_command(path)}\n"
        "```\n\n"
        "---"
    )


def _fallback_template() -> Template:
    template = resources.files("agent_voice")
    for part in _FALLBACK_TEMPLATE_RESOURCE:
        template = template.joinpath(part)
    return Template(template.read_text(encoding="utf-8"))


def _terminal_command(path: Path) -> str:
    if os.name == "nt":
        argument = subprocess.list2cmdline([str(path)])
        return f"agent-voice play {argument}"
    return shlex.join(["agent-voice", "play", str(path)])
