from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import __version__

PYPI_URL = "https://pypi.org/pypi/agent-voice/json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def notify_if_update_available() -> None:
    if not sys.stderr.isatty():
        return

    now = time.time()
    cache = _read_cache()
    changed = False
    latest = cache.get("latest")
    if now - _timestamp(cache.get("checked_at")) >= CHECK_INTERVAL_SECONDS:
        latest = _latest_version() or latest
        cache.update(checked_at=now, latest=latest)
        changed = True

    latest_version = _stable_version(latest) if isinstance(latest, str) else None
    current_version = _stable_version(__version__)
    if (
        latest_version is not None
        and current_version is not None
        and latest_version > current_version
        and now - _timestamp(cache.get("notified_at")) >= CHECK_INTERVAL_SECONDS
    ):
        print(
            f"Agent Voice {latest} is available; run: agent-voice update",
            file=sys.stderr,
        )
        cache["notified_at"] = now
        changed = True

    if changed:
        _write_cache(cache)


def run_update() -> int:
    prefix = Path(sys.prefix)
    if (prefix / "pipx_metadata.json").is_file():
        command = _manager_command("pipx", "upgrade", "agent-voice")
    elif (prefix / "uv-receipt.toml").is_file():
        command = _manager_command("uv", "tool", "upgrade", "agent-voice")
    else:
        raise RuntimeError(
            "Could not identify a uv or pipx installation; update Agent Voice "
            "with the tool that installed it"
        )
    return subprocess.run(command, check=False).returncode


def _manager_command(name: str, *arguments: str) -> list[str]:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(
            f"{name} is required to update this Agent Voice installation"
        )
    return [executable, *arguments]


def _latest_version() -> str | None:
    request = urllib.request.Request(
        PYPI_URL, headers={"User-Agent": f"agent-voice/{__version__}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=1) as response:
            latest = json.load(response)["info"]["version"]
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return (
        latest
        if isinstance(latest, str) and _stable_version(latest) is not None
        else None
    )


def _stable_version(version: str) -> tuple[int, int, int] | None:
    # ponytail: stable releases only; use packaging.version if prereleases are added.
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return None
    return tuple(map(int, version.split(".")))


def _cache_path() -> Path:
    configured = os.environ.get("AGENT_VOICE_HOME")
    if configured:
        return Path(configured).expanduser().resolve() / "update-check.json"
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "agent-voice" / "update-check.json"


def _read_cache() -> dict[str, object]:
    try:
        cache = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cache if isinstance(cache, dict) else {}


def _write_cache(cache: dict[str, object]) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def _timestamp(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
