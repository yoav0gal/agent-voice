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


def resolved_recording_dir(
    configured_output_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve the active managed recording directory."""
    if os.environ.get("AGENT_VOICE_RECORDING_DIR"):
        return recording_dir()
    if configured_output_dir is not None:
        return Path(configured_output_dir).expanduser().resolve()
    return recording_dir()


def model_dir() -> Path:
    configured = os.environ.get("AGENT_VOICE_MODEL_DIR")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else project_root() / "models"
    )


def pending_generation_path(recording: Path) -> Path:
    return _generation_path(recording, "pending")


def streaming_pcm_path(recording: Path) -> Path:
    return _generation_path(recording, "pcm")


def _generation_path(recording: Path, suffix: str) -> Path:
    path = recording.expanduser().resolve()
    return path.with_name(f".{path.name}.{suffix}")
