from __future__ import annotations

import html
import os
import secrets
import shlex
import subprocess
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template
from urllib.parse import quote

from .audio import CONTENT_TYPES


_TEMPLATE_RESOURCE = ("templates", "recording.html")


@dataclass(frozen=True)
class Delivery:
    fallback_markdown: str
    warning: str | None = None


def prepare_delivery(
    recording: Path,
    text: str,
    *,
    audio_format: str | None = None,
) -> Delivery:
    """Create a local HTML player or fall back to portable recording links."""
    path = recording.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Recording not found: {path}")
    if not isinstance(text, str):
        raise ValueError("Recording text must be a string")

    resolved_format = (audio_format or path.suffix.lstrip(".")).lower()
    media_type = CONTENT_TYPES.get(resolved_format)
    if media_type is None:
        raise ValueError(f"Unsupported recording format: {resolved_format or '(none)'}")

    try:
        player_path = _create_player(path, text, media_type)
    except OSError as error:
        return Delivery(
            _fallback_markdown(path),
            f"Could not create HTML player; using media fallback ({error})",
        )
    return Delivery(_fallback_markdown(path, player_path))


def _fallback_markdown(path: Path, player_path: Path | None = None) -> str:
    if player_path is None:
        listen = f"Listen: [media]({path.as_uri()})"
    else:
        listen = (
            f"Listen: [browser]({player_path.as_uri()})"
            f" · [media]({path.as_uri()})"
        )
    return (
        "---\n\n"
        f"Agent Voice recording {path.name}\n"
        f"{listen}\n"
        "```sh\n"
        f"{_terminal_command(path)}\n"
        "```\n\n"
        "---"
    )


def _create_player(recording: Path, text: str, media_type: str) -> Path:
    player_path = _reserve_player_path(recording)
    temporary: Path | None = None
    try:
        document = _player_template().substitute(
            PAGE_TITLE=html.escape(
                f"{recording.name} · Agent Voice",
                quote=True,
            ),
            RECORDING_NAME=html.escape(recording.name, quote=True),
            MEDIA_SOURCE=html.escape(quote(recording.name), quote=True),
            MEDIA_TYPE=html.escape(media_type, quote=True),
            RESPONSE_TEXT=html.escape(text),
        )
        temporary = player_path.with_name(
            f".{player_path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, player_path)
        return player_path
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        player_path.unlink(missing_ok=True)
        raise


def _reserve_player_path(recording: Path) -> Path:
    base = recording.with_suffix(".html")
    candidate = base
    collision = 2
    while True:
        try:
            descriptor = os.open(
                candidate,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            candidate = base.with_name(f"{base.stem}-{collision}{base.suffix}")
            collision += 1
        else:
            os.close(descriptor)
            return candidate


def _player_template() -> Template:
    template = resources.files("agent_voice")
    for part in _TEMPLATE_RESOURCE:
        template = template.joinpath(part)
    return Template(template.read_text(encoding="utf-8"))


def _terminal_command(path: Path) -> str:
    if os.name == "nt":
        argument = subprocess.list2cmdline([str(path)])
        return f"agent-voice play {argument}"
    return shlex.join(["agent-voice", "play", str(path)])
