from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    """Return the writable Agent Voice data root."""
    configured = os.environ.get("AGENT_VOICE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()

    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").is_file() and (checkout / "agent-voice").is_file():
        return checkout

    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = (
            Path(local_app_data).expanduser()
            if local_app_data
            else Path.home() / "AppData" / "Local"
        )
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        base = (
            Path(xdg_data_home).expanduser()
            if xdg_data_home
            else Path.home() / ".local" / "share"
        )
    return (base / "agent-voice").resolve()


def recording_dir() -> Path:
    configured = os.environ.get("AGENT_VOICE_RECORDING_DIR")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else project_root() / "recordings"
    )


def model_dir() -> Path:
    configured = os.environ.get("AGENT_VOICE_MODEL_DIR")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else project_root() / "models"
    )
