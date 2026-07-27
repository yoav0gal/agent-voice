from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


def prepare_delivery(recording: Path) -> dict[str, str]:
    """Return a portable Markdown fallback for an existing local recording."""
    path = recording.expanduser().resolve()
    fallback_markdown = (
        f"Agent Voice recording {path.name}\n"
        f"Listen: [media]({path.as_uri()})\n"
        "```sh\n"
        f"{_terminal_command(path)}\n"
        "```"
    )
    return {"fallback_markdown": fallback_markdown}


def _terminal_command(path: Path) -> str:
    if os.name == "nt":
        argument = subprocess.list2cmdline([str(path)])
        return f"agent-voice play {argument}"
    return shlex.join(["agent-voice", "play", str(path)])
