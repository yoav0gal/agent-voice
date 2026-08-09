from __future__ import annotations

import ctypes
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .audio import PLAYBACK_ACTIONS
from .viewer import Viewer, active_viewer, valid_control_token


_SCHEME = "agent-voice"
_APP_NAME = "Agent Voice Controls.app"
_BUNDLE_ID = "com.yoavgal.agent-voice.link-handler"
_OWNED_BUNDLE_IDS = {_BUNDLE_ID, "com.yoavgal.agent-voice.controls"}
_LINUX_DESKTOP_NAME = "agent-voice-controls.desktop"
_WINDOWS_REGISTRY_PATH = rf"Software\Classes\{_SCHEME}"
_WINDOWS_OWNER_VALUE = "AgentVoiceOwned"
_LSREGISTER = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)


def handler_path() -> Path | str:
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "agent-voice"
            / "integrations"
            / _APP_NAME
        )
    if sys.platform.startswith("linux"):
        data_home = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        ).expanduser()
        return data_home / "applications" / _LINUX_DESKTOP_NAME
    if sys.platform == "win32":
        return rf"HKCU\{_WINDOWS_REGISTRY_PATH}"
    raise RuntimeError(f"Agent Voice control links are unsupported on {sys.platform}")


def install_handler() -> Path | str:
    if sys.platform == "darwin":
        return _install_macos_handler()
    if sys.platform.startswith("linux"):
        return _install_linux_handler()
    if sys.platform == "win32":
        return _install_windows_handler()
    raise RuntimeError(f"Agent Voice control links are unsupported on {sys.platform}")


def _install_macos_handler() -> Path:
    destination = handler_path()
    assert isinstance(destination, Path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        candidate = Path(temporary) / _APP_NAME
        script = (
            "on dispatchControl(commandName, controlValue)\n"
            'do shell script "/usr/bin/nohup " & quoted form of '
            f'"{_applescript_string(sys.executable)}" & '
            '" -m agent_voice " & commandName & " " & '
            "quoted form of controlValue & "
            '" >/dev/null 2>&1 &"\n'
            "end dispatchControl\n"
            "on open location theURL\n"
            'dispatchControl("control-url", theURL)\n'
            "end open location"
        )
        _run(["/usr/bin/osacompile", "-o", str(candidate), "-e", script])
        info_path = candidate / "Contents" / "Info.plist"
        with info_path.open("rb") as stream:
            info = plistlib.load(stream)
        info.update(
            {
                "CFBundleIdentifier": _BUNDLE_ID,
                "CFBundleName": "Agent Voice Controls",
                "LSUIElement": True,
                "CFBundleURLTypes": [
                    {
                        "CFBundleTypeRole": "Viewer",
                        "CFBundleURLName": _BUNDLE_ID,
                        "CFBundleURLSchemes": [_SCHEME],
                    }
                ],
            }
        )
        with info_path.open("wb") as stream:
            plistlib.dump(info, stream)
        _run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(candidate)])
        _run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(candidate)])

        previous = destination.with_name(f".{destination.name}.previous")
        if previous.exists() or previous.is_symlink():
            _require_our_handler(previous)
        if destination.exists() or destination.is_symlink():
            _require_our_handler(destination)
            if previous.exists():
                shutil.rmtree(previous)
            destination.replace(previous)
        try:
            candidate.replace(destination)
            _run([str(_LSREGISTER), "-f", str(destination)])
            _set_default_handler()
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            if previous.exists():
                previous.replace(destination)
            raise
        shutil.rmtree(previous, ignore_errors=True)
    return destination


def uninstall_handler() -> bool:
    if sys.platform == "darwin":
        return _uninstall_macos_handler()
    if sys.platform.startswith("linux"):
        return _uninstall_linux_handler()
    if sys.platform == "win32":
        return _uninstall_windows_handler()
    raise RuntimeError(f"Agent Voice control links are unsupported on {sys.platform}")


def _uninstall_macos_handler() -> bool:
    destination = handler_path()
    assert isinstance(destination, Path)
    if not destination.exists() and not destination.is_symlink():
        return False
    _require_our_handler(destination)
    _run([str(_LSREGISTER), "-u", str(destination)])
    shutil.rmtree(destination)
    return True


def _install_linux_handler() -> Path:
    destination = handler_path()
    assert isinstance(destination, Path)
    xdg_mime = shutil.which("xdg-mime")
    if xdg_mime is None:
        raise RuntimeError("xdg-mime is required to register Agent Voice controls")
    if destination.exists() or destination.is_symlink():
        _require_our_linux_handler(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        candidate = Path(temporary) / destination.name
        candidate.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Agent Voice Controls\n"
            "Comment=Playback controls for Agent Voice\n"
            f"Exec={_desktop_exec(sys.executable)} -m agent_voice control-url %u\n"
            "Terminal=false\n"
            "NoDisplay=true\n"
            f"MimeType=x-scheme-handler/{_SCHEME};\n"
            "X-Agent-Voice-Owned=true\n",
            encoding="utf-8",
        )
        candidate.chmod(0o755)
        previous = destination.with_name(f".{destination.name}.previous")
        if previous.exists() or previous.is_symlink():
            _require_our_linux_handler(previous)
        if destination.exists() or destination.is_symlink():
            previous.unlink(missing_ok=True)
            destination.replace(previous)
        try:
            candidate.replace(destination)
            _run(
                [
                    xdg_mime,
                    "default",
                    destination.name,
                    f"x-scheme-handler/{_SCHEME}",
                ]
            )
            _update_linux_desktop_database(destination.parent)
        except BaseException:
            destination.unlink(missing_ok=True)
            if previous.exists():
                previous.replace(destination)
            raise
        previous.unlink(missing_ok=True)
    return destination


def _uninstall_linux_handler() -> bool:
    destination = handler_path()
    assert isinstance(destination, Path)
    if not destination.exists() and not destination.is_symlink():
        return False
    _require_our_linux_handler(destination)
    destination.unlink()
    _update_linux_desktop_database(destination.parent)
    return True


def _install_windows_handler() -> str:
    winreg = _winreg()
    if _windows_handler_exists(winreg) and not _windows_handler_owned(winreg):
        raise RuntimeError(
            f"Refusing to replace unrecognized handler: {handler_path()}"
        )
    executable = _windows_handler_executable()
    values = {
        _WINDOWS_REGISTRY_PATH: {
            None: "URL:Agent Voice playback controls",
            "URL Protocol": "",
            _WINDOWS_OWNER_VALUE: "1",
        },
        rf"{_WINDOWS_REGISTRY_PATH}\DefaultIcon": {None: sys.executable},
        rf"{_WINDOWS_REGISTRY_PATH}\shell\open\command": {
            None: f'"{executable}" -m agent_voice control-url "%1"'
        },
    }
    for key_path, entries in values.items():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            for name, value in entries.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    return str(handler_path())


def _windows_handler_executable() -> str:
    windowed = Path(sys.executable).with_name("pythonw.exe")
    return str(windowed) if windowed.is_file() else sys.executable


def _uninstall_windows_handler() -> bool:
    winreg = _winreg()
    if not _windows_handler_exists(winreg):
        return False
    if not _windows_handler_owned(winreg):
        raise RuntimeError(f"Refusing to remove unrecognized handler: {handler_path()}")
    for key_path in (
        rf"{_WINDOWS_REGISTRY_PATH}\shell\open\command",
        rf"{_WINDOWS_REGISTRY_PATH}\shell\open",
        rf"{_WINDOWS_REGISTRY_PATH}\shell",
        rf"{_WINDOWS_REGISTRY_PATH}\DefaultIcon",
        _WINDOWS_REGISTRY_PATH,
    ):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            pass
    return True


def _require_our_linux_handler(desktop: Path) -> None:
    if desktop.is_symlink():
        raise RuntimeError(f"Refusing to replace symlink: {desktop}")
    try:
        owned = "X-Agent-Voice-Owned=true" in desktop.read_text(encoding="utf-8")
    except OSError:
        owned = False
    if not owned:
        raise RuntimeError(f"Refusing to replace unrecognized handler: {desktop}")


def _update_linux_desktop_database(directory: Path) -> None:
    update_database = shutil.which("update-desktop-database")
    if update_database is not None:
        _run([update_database, str(directory)])


def _desktop_exec(executable: str) -> str:
    escaped = []
    for character in executable:
        if character == "\\":
            escaped.append("\\" * 4)
        elif character == '"':
            escaped.append("\\" * 3 + character)
        elif character in {"`", "$"}:
            escaped.append("\\" * 2 + character)
        elif character == "%":
            escaped.append("%%")
        else:
            escaped.append(character)
    return f'"{"".join(escaped)}"'


def _winreg():
    try:
        import winreg
    except ImportError as error:  # pragma: no cover - only reachable off Windows
        raise RuntimeError("Windows registry support is unavailable") from error
    return winreg


def _windows_handler_exists(winreg) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_REGISTRY_PATH):
            return True
    except OSError:
        return False


def _windows_handler_owned(winreg) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_REGISTRY_PATH) as key:
            return winreg.QueryValueEx(key, _WINDOWS_OWNER_VALUE)[0] == "1"
    except OSError:
        return False


def parse_control_url(value: str) -> tuple[str, str]:
    try:
        url = urlsplit(value)
        if url.port is not None:
            raise ValueError
        parts = [unquote(part, errors="strict") for part in url.path.split("/")[1:]]
    except (UnicodeError, ValueError) as error:
        raise ValueError("Invalid Agent Voice control link") from error
    if (
        url.scheme != _SCHEME
        or url.netloc != "control"
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or len(parts) != 2
        or not valid_control_token(parts[0])
        or parts[1] not in PLAYBACK_ACTIONS
    ):
        raise ValueError("Invalid Agent Voice control link")
    return parts[0], parts[1]


def trigger_control_url(value: str) -> dict[str, object]:
    token, action = parse_control_url(value)
    viewer = active_viewer()
    if viewer is None or viewer.url is None:
        raise RuntimeError("Recording viewer is not running")
    return _trigger_control(viewer, token, action)


def _trigger_control(viewer: Viewer, token: str, action: str) -> dict[str, object]:
    request = urllib.request.Request(
        f"{viewer.url}/control/{token}/{action}",
        headers={"X-Agent-Voice-Control": "1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError("Playback control failed") from error
    if not isinstance(result, dict):
        raise RuntimeError("Playback control returned an invalid response")
    return result


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "").strip()
        raise RuntimeError(
            f"Could not update control handler{': ' + detail if detail else ''}"
        ) from error


def _require_our_handler(app: Path) -> None:
    if app.is_symlink():
        raise RuntimeError(f"Refusing to replace symlink: {app}")
    try:
        with (app / "Contents" / "Info.plist").open("rb") as stream:
            owned = plistlib.load(stream).get("CFBundleIdentifier") in _OWNED_BUNDLE_IDS
    except (OSError, plistlib.InvalidFileException):
        owned = False
    if not owned:
        raise RuntimeError(f"Refusing to replace unrecognized app: {app}")


def _applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _set_default_handler() -> None:
    core_foundation = ctypes.CDLL(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
    launch_services = ctypes.CDLL(
        "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
        "LaunchServices.framework/LaunchServices"
    )
    create = core_foundation.CFStringCreateWithCString
    create.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    create.restype = ctypes.c_void_p
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    set_handler = launch_services.LSSetDefaultHandlerForURLScheme
    set_handler.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    set_handler.restype = ctypes.c_int32
    scheme = create(None, _SCHEME.encode(), 0x08000100)
    bundle = create(None, _BUNDLE_ID.encode(), 0x08000100)
    try:
        scheme_status = set_handler(scheme, bundle)
    finally:
        release(scheme)
        release(bundle)
    if scheme_status != 0:
        raise RuntimeError(
            f"Could not register Agent Voice controls (URL status {scheme_status})"
        )
