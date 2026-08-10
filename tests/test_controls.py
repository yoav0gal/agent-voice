from __future__ import annotations

import json
import plistlib
import sys
from pathlib import Path

import pytest

from agent_voice import cli, controls

TOKEN = "abcdefghijklmnopqrstuvwx"


def test_control_url_parser_accepts_only_scoped_agent_voice_links():
    assert controls.parse_control_url(f"agent-voice://control/{TOKEN}/toggle") == (
        TOKEN,
        "toggle",
    )
    assert controls.parse_control_url(f"agent-voice://control/{TOKEN}/faster") == (
        TOKEN,
        "faster",
    )

    for invalid in (
        f"https://control/{TOKEN}/toggle",
        f"agent-voice://other/{TOKEN}/toggle",
        f"agent-voice://control/{TOKEN}/delete",
        f"agent-voice://control/{TOKEN}/toggle?again=1",
        f"agent-voice://control/{TOKEN}/toggle#again",
        f"agent-voice://user@control/{TOKEN}/toggle",
        "agent-voice://control/short/toggle",
    ):
        with pytest.raises(ValueError, match="Invalid Agent Voice control link"):
            controls.parse_control_url(invalid)


def test_install_handler_builds_registers_and_reuses_owned_macos_app(
    tmp_path, monkeypatch
):
    app = tmp_path / "Agent Voice Controls.app"
    commands = []

    def run(command):
        commands.append(command)
        if command[0] == "/usr/bin/osacompile":
            candidate = Path(command[command.index("-o") + 1])
            (candidate / "Contents").mkdir(parents=True)
            with (candidate / "Contents" / "Info.plist").open("wb") as stream:
                plistlib.dump({}, stream)

    monkeypatch.setattr(controls.sys, "platform", "darwin")
    monkeypatch.setattr(controls, "handler_path", lambda: app)
    monkeypatch.setattr(controls, "_run", run)
    defaults = []
    monkeypatch.setattr(controls, "_set_default_handler", lambda: defaults.append(True))

    assert controls.install_handler() == app
    assert controls.install_handler() == app

    with (app / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["CFBundleIdentifier"] == "com.yoavgal.agent-voice.link-handler"
    assert info["CFBundleURLTypes"][0]["CFBundleURLSchemes"] == ["agent-voice"]
    assert "CFBundleDocumentTypes" not in info
    assert "UTExportedTypeDeclarations" not in info
    script = commands[0][-1]
    assert "on open location theURL" in script
    assert "on open controlFiles" not in script
    assert "quoted form of controlValue" in script
    assert sum(command[0].endswith("lsregister") for command in commands) == 2
    assert defaults == [True, True]


def test_install_handler_preserves_unowned_previous_app(tmp_path, monkeypatch):
    app = tmp_path / "Agent Voice Controls.app"
    previous = tmp_path / ".Agent Voice Controls.app.previous"
    (previous / "Contents").mkdir(parents=True)
    marker = previous / "keep.txt"
    marker.write_text("user data")
    with (previous / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleIdentifier": "example.unowned"}, stream)

    def run(command):
        if command[0] == "/usr/bin/osacompile":
            candidate = Path(command[command.index("-o") + 1])
            (candidate / "Contents").mkdir(parents=True)
            with (candidate / "Contents" / "Info.plist").open("wb") as stream:
                plistlib.dump({}, stream)

    monkeypatch.setattr(controls.sys, "platform", "darwin")
    monkeypatch.setattr(controls, "handler_path", lambda: app)
    monkeypatch.setattr(controls, "_run", run)

    with pytest.raises(RuntimeError, match="unrecognized app"):
        controls.install_handler()

    assert marker.read_text() == "user data"
    assert not app.exists()


def test_uninstall_handler_is_idempotent_and_removes_only_owned_app(
    tmp_path, monkeypatch
):
    app = tmp_path / "Agent Voice Controls.app"
    (app / "Contents").mkdir(parents=True)
    with (app / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump(
            {"CFBundleIdentifier": "com.yoavgal.agent-voice.link-handler"}, stream
        )
    commands = []
    monkeypatch.setattr(controls.sys, "platform", "darwin")
    monkeypatch.setattr(controls, "handler_path", lambda: app)
    monkeypatch.setattr(controls, "_run", commands.append)

    assert controls.uninstall_handler() is True
    assert controls.uninstall_handler() is False
    assert commands == [[str(controls._LSREGISTER), "-u", str(app)]]
    assert not app.exists()


def test_uninstall_handler_refuses_unowned_app(tmp_path, monkeypatch):
    app = tmp_path / "Agent Voice Controls.app"
    (app / "Contents").mkdir(parents=True)
    with (app / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleIdentifier": "example.unowned"}, stream)
    monkeypatch.setattr(controls.sys, "platform", "darwin")
    monkeypatch.setattr(controls, "handler_path", lambda: app)

    with pytest.raises(RuntimeError, match="unrecognized app"):
        controls.uninstall_handler()

    assert app.exists()


def test_uninstall_handler_keeps_app_when_unregister_fails(tmp_path, monkeypatch):
    app = tmp_path / "Agent Voice Controls.app"
    (app / "Contents").mkdir(parents=True)
    with (app / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump(
            {"CFBundleIdentifier": "com.yoavgal.agent-voice.link-handler"}, stream
        )
    monkeypatch.setattr(controls.sys, "platform", "darwin")
    monkeypatch.setattr(controls, "handler_path", lambda: app)
    monkeypatch.setattr(
        controls,
        "_run",
        lambda _command: (_ for _ in ()).throw(RuntimeError("unregister failed")),
    )

    with pytest.raises(RuntimeError, match="unregister failed"):
        controls.uninstall_handler()

    assert app.exists()


def test_handler_ownership_check_rejects_symlinks(tmp_path):
    target = tmp_path / "owned.app"
    (target / "Contents").mkdir(parents=True)
    with (target / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump(
            {"CFBundleIdentifier": "com.yoavgal.agent-voice.link-handler"}, stream
        )
    link = tmp_path / "handler.app"
    link.symlink_to(target)

    with pytest.raises(RuntimeError, match="symlink"):
        controls._require_our_handler(link)


def test_linux_handler_installs_updates_and_uninstalls(tmp_path, monkeypatch):
    data_home = tmp_path / "data home"
    executable = tmp_path / "bin with $ % and `" / "python"
    commands = []
    monkeypatch.setattr(controls.sys, "platform", "linux")
    monkeypatch.setattr(controls.sys, "executable", str(executable))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setattr(
        controls.shutil,
        "which",
        lambda name: (
            f"/usr/bin/{name}"
            if name in {"xdg-mime", "update-desktop-database"}
            else None
        ),
    )
    monkeypatch.setattr(controls, "_run", commands.append)

    desktop = controls.install_handler()
    assert desktop == data_home / "applications" / "agent-voice-controls.desktop"
    contents = desktop.read_text(encoding="utf-8")
    assert "X-Agent-Voice-Owned=true" in contents
    assert "MimeType=x-scheme-handler/agent-voice;" in contents
    assert (
        f"Exec={controls._desktop_exec(str(executable))} -m agent_voice control-url %u"
    ) in contents
    assert desktop.stat().st_mode & 0o111
    assert commands[:2] == [
        [
            "/usr/bin/xdg-mime",
            "default",
            desktop.name,
            "x-scheme-handler/agent-voice",
        ],
        ["/usr/bin/update-desktop-database", str(desktop.parent)],
    ]

    assert controls.install_handler() == desktop
    assert controls.uninstall_handler() is True
    assert controls.uninstall_handler() is False
    assert not desktop.exists()


def test_linux_handler_refuses_unowned_desktop_file(tmp_path, monkeypatch):
    desktop = tmp_path / "applications" / "agent-voice-controls.desktop"
    desktop.parent.mkdir()
    desktop.write_text("[Desktop Entry]\nName=Someone Else\n", encoding="utf-8")
    monkeypatch.setattr(controls.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(controls.shutil, "which", lambda _name: "/usr/bin/xdg-mime")

    with pytest.raises(RuntimeError, match="unrecognized handler"):
        controls.install_handler()
    with pytest.raises(RuntimeError, match="unrecognized handler"):
        controls.uninstall_handler()
    assert "Someone Else" in desktop.read_text(encoding="utf-8")


class _RegistryKey:
    def __init__(self, registry, path):
        self.registry = registry
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = "REG_SZ"

    def __init__(self):
        self.keys = {}

    def CreateKey(self, root, path):
        assert root == self.HKEY_CURRENT_USER
        parts = path.split("\\")
        for end in range(1, len(parts) + 1):
            self.keys.setdefault("\\".join(parts[:end]), {})
        return _RegistryKey(self, path)

    def OpenKey(self, root, path):
        assert root == self.HKEY_CURRENT_USER
        if path not in self.keys:
            raise FileNotFoundError(path)
        return _RegistryKey(self, path)

    def QueryValueEx(self, key, name):
        try:
            return self.keys[key.path][name], self.REG_SZ
        except KeyError as error:
            raise FileNotFoundError(name) from error

    def SetValueEx(self, key, name, reserved, kind, value):
        assert reserved == 0
        assert kind == self.REG_SZ
        self.keys[key.path][name] = value

    def DeleteKey(self, root, path):
        assert root == self.HKEY_CURRENT_USER
        if any(key.startswith(f"{path}\\") for key in self.keys):
            raise OSError(f"Registry key has children: {path}")
        del self.keys[path]


def test_windows_handler_installs_updates_and_uninstalls(tmp_path, monkeypatch):
    executable = tmp_path / "Python with spaces" / "python.exe"
    windowed = executable.with_name("pythonw.exe")
    windowed.parent.mkdir(parents=True)
    windowed.touch()
    registry = _FakeWinreg()
    monkeypatch.setattr(controls.sys, "platform", "win32")
    monkeypatch.setattr(controls.sys, "executable", str(executable))
    monkeypatch.setitem(sys.modules, "winreg", registry)

    location = controls.install_handler()
    base = r"Software\Classes\agent-voice"
    assert location == rf"HKCU\{base}"
    assert registry.keys[base] == {
        None: "URL:Agent Voice playback controls",
        "URL Protocol": "",
        "AgentVoiceOwned": "1",
    }
    assert registry.keys[rf"{base}\shell\open\command"][None] == (
        f'"{windowed}" -m agent_voice control-url "%1"'
    )

    assert controls.install_handler() == location
    assert controls.uninstall_handler() is True
    assert controls.uninstall_handler() is False
    assert base not in registry.keys


def test_windows_handler_requires_windowless_python(tmp_path, monkeypatch):
    executable = tmp_path / "python.exe"
    monkeypatch.setattr(controls.sys, "executable", str(executable))

    with pytest.raises(RuntimeError, match="pythonw.exe is required"):
        controls._windows_handler_executable()


def test_windows_handler_refuses_unowned_registry_key(monkeypatch):
    registry = _FakeWinreg()
    base = r"Software\Classes\agent-voice"
    registry.CreateKey(registry.HKEY_CURRENT_USER, base)
    registry.keys[base][None] = "Someone else's handler"
    monkeypatch.setattr(controls.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", registry)

    with pytest.raises(RuntimeError, match="unrecognized handler"):
        controls.install_handler()
    with pytest.raises(RuntimeError, match="unrecognized handler"):
        controls.uninstall_handler()
    assert registry.keys[base][None] == "Someone else's handler"


def test_controls_reject_unsupported_platform(monkeypatch):
    monkeypatch.setattr(controls.sys, "platform", "freebsd")
    with pytest.raises(RuntimeError, match="unsupported on freebsd"):
        controls.install_handler()


def test_controls_cli_installs_handler_and_dispatches_links(
    tmp_path, monkeypatch, capsys
):
    app = tmp_path / "Agent Voice Controls.app"
    monkeypatch.setattr(controls, "handler_path", lambda: app)
    monkeypatch.setattr(controls, "install_handler", lambda: app)
    monkeypatch.setattr(controls, "uninstall_handler", lambda: True)
    monkeypatch.setattr(
        controls,
        "trigger_control_url",
        lambda url: {"recording": url, "playing": True},
    )
    cli.main(["controls", "install", "--json"])
    installed = capsys.readouterr().out
    assert '"scheme": "agent-voice"' in installed
    cli.main(["controls", "uninstall", "--json"])
    assert json.loads(capsys.readouterr().out) == {
        "installed": False,
        "scheme": "agent-voice",
        "path": str(app),
        "removed": True,
    }
    cli.main(["control-url", f"agent-voice://control/{TOKEN}/toggle", "--json"])
    assert '"playing": true' in capsys.readouterr().out
