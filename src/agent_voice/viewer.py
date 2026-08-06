from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from filelock import FileLock

from .media import CONTENT_TYPES
from .paths import project_root, recording_dir


_TRANSCRIPT_DIRECTORY = ".agent-voice-viewer"
_PLAYER_DIRECTORY = "players"
_RECORDING_RETENTION_SECONDS = (4 * 24 + 18) * 60 * 60
_STARTUP_TIMEOUT_SECONDS = 15.0
_STARTUP_HEALTH_TIMEOUT_SECONDS = 1.0
VIEWER_PROTOCOL = 3


@dataclass(frozen=True)
class Viewer:
    recordings_dir: Path
    port: int | None = None
    pid: int | None = None

    @property
    def running(self) -> bool:
        return self.port is not None

    @property
    def url(self) -> str | None:
        return None if self.port is None else f"http://127.0.0.1:{self.port}"

    def to_dict(self) -> dict[str, object]:
        return {
            "running": self.running,
            "url": self.url,
            "port": self.port,
            "pid": self.pid,
            "recordings_dir": str(self.recordings_dir),
        }


def ensure_viewer(recordings_dir: Path | None = None) -> Viewer:
    # ponytail: prefer one stable port and let the OS choose only on collision.
    root = (recordings_dir or recording_dir()).expanduser().resolve()
    with FileLock(project_root() / "viewer.lock", timeout=5):
        state = _state()
        current = _running(state)
        if current and current.recordings_dir == root:
            return current
        if current or _running(state, require_protocol=False):
            _stop(state)

        state_path = project_root() / "viewer.json"
        state_path.unlink(missing_ok=True)
        root.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "agent_voice.viewer_server",
                str(root),
                str(state_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **(
                {
                    "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.DETACHED_PROCESS
                }
                if os.name == "nt"
                else {"start_new_session": True}
            ),
        )
        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            returncode = process.poll()
            if returncode is not None:
                break
            current = _running(
                _state(),
                timeout=_STARTUP_HEALTH_TIMEOUT_SECONDS,
            )
            if current:
                return current
            time.sleep(0.05)
        returncode = process.poll()
        if returncode is None:
            startup_state = _state()
            process.terminate()
            process.wait(timeout=2)
            phase = startup_state.get("status", "state unavailable")
            raise RuntimeError(
                "Recording viewer did not become healthy within "
                f"{_STARTUP_TIMEOUT_SECONDS:g} seconds "
                f"(startup status: {phase})"
            )
        raise RuntimeError(
            f"Recording viewer exited during startup with status {returncode}"
        )


def stop_viewer() -> Viewer:
    state = _state()
    current = _running(state, require_protocol=False)
    if not current:
        (project_root() / "viewer.json").unlink(missing_ok=True)
        return Viewer(_root(state))
    _stop(state)
    return Viewer(current.recordings_dir)


def publish_recording(
    recording: Path,
    audio_format: str,
    recordings_dir: Path | None = None,
) -> Path:
    source = recording.expanduser().resolve()
    root = (recordings_dir or recording_dir()).expanduser().resolve()
    suffix = f".{audio_format.lower()}"
    if audio_format.lower() not in CONTENT_TYPES:
        raise ValueError(f"Unsupported recording format: {audio_format}")
    if source.parent == root and source.suffix.lower() == suffix:
        return source

    root.mkdir(parents=True, exist_ok=True)
    base = root / (
        source.name if source.suffix.lower() == suffix else f"{source.name}{suffix}"
    )
    destination = base
    counter = 2
    while True:
        try:
            handle = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            destination = base.with_name(f"{base.stem}-{counter}{base.suffix}")
            counter += 1
        else:
            os.close(handle)
            break
    handle, temporary_name = tempfile.mkstemp(dir=root)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def publish_transcript(recording: Path, text: str) -> Path:
    return _write_text(transcript_path(recording), text)


def publish_source(recording: Path, text: str) -> Path:
    return _write_text(source_path(recording), text)


def publish_language(recording: Path, language: str) -> Path:
    return _write_text(language_path(recording), language)


def _write_text(destination: Path, text: str) -> Path:
    if not isinstance(text, str):
        raise ValueError("Recording text must be a string")

    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary_name = tempfile.mkstemp(dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def publish_player(recording: Path, text: str) -> str:
    publish_transcript(recording, text)
    root = transcript_path(recording).parent / _PLAYER_DIRECTORY
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = recording.stem
    name = base
    counter = 2
    while True:
        mapping = root / f"{name}.txt"
        try:
            handle = os.open(
                mapping,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            try:
                if mapping.read_text(encoding="utf-8") == recording.name:
                    return f"{name}.html"
            except OSError:
                pass
            name = f"{base}-{counter}"
            counter += 1
        else:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(recording.name)
                stream.flush()
                os.fsync(stream.fileno())
            return f"{name}.html"


def transcript_path(recording: Path) -> Path:
    path = recording.expanduser().resolve()
    digest = hashlib.sha256(path.name.encode()).hexdigest()
    return path.parent / _TRANSCRIPT_DIRECTORY / f"{digest}.txt"


def source_path(recording: Path) -> Path:
    path = recording.expanduser().resolve()
    return path.with_name(f"{path.name}.txt")


def language_path(recording: Path) -> Path:
    return transcript_path(recording).with_suffix(".lang")


def delete_expired_recordings(recordings: Path, *, now: float | None = None) -> None:
    cutoff = (time.time() if now is None else now) - _RECORDING_RETENTION_SECONDS
    try:
        # ponytail: a direct top-level scan is enough for the managed folder.
        for path in recordings.iterdir():
            try:
                if (
                    path.suffix.lower().lstrip(".") in CONTENT_TYPES
                    and source_path(path).is_file()
                    and transcript_path(path).is_file()
                    and language_path(path).is_file()
                    and path.stat().st_mtime <= cutoff
                ):
                    path.unlink()
            except OSError:
                continue
    except OSError:
        return


def player_mapping_path(recordings: Path, player_name: str) -> Path:
    return recordings / _TRANSCRIPT_DIRECTORY / _PLAYER_DIRECTORY / f"{player_name}.txt"


def recording_urls(
    viewer: Viewer,
    recording: Path,
    player_name: str,
) -> tuple[str, str]:
    if not viewer.url:
        raise RuntimeError("Recording viewer is not running")
    name = quote(recording.name, safe="")
    return (
        f"{viewer.url}/player/{quote(player_name, safe='')}",
        f"{viewer.url}/recordings/{name}",
    )


def _state() -> dict[str, object]:
    try:
        value = json.loads((project_root() / "viewer.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _running(
    state: dict[str, object],
    *,
    timeout: float = 0.25,
    require_protocol: bool = True,
) -> Viewer | None:
    try:
        port, pid = int(state["port"]), int(state["pid"])
        root = _root(state)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=timeout
        ) as response:
            health = json.loads(response.read())
    except (KeyError, ValueError, OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if (
        health.get("service") != "agent-voice-viewer"
        or health.get("pid") != pid
        or (require_protocol and health.get("protocol") != VIEWER_PROTOCOL)
    ):
        return None
    return Viewer(root, port, pid)


def _stop(state: dict[str, object]) -> None:
    pid = int(state["pid"])
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if not _running(state, require_protocol=False):
            (project_root() / "viewer.json").unlink(missing_ok=True)
            return
        time.sleep(0.05)
    raise RuntimeError("Recording viewer did not stop")


def _root(state: dict[str, object]) -> Path:
    value = state.get("recordings_dir")
    return (
        Path(value).resolve() if isinstance(value, str) else recording_dir().resolve()
    )
