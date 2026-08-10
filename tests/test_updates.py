from __future__ import annotations

import json
from types import SimpleNamespace

from agent_voice import cli, updates


def test_update_notice_is_cached_for_a_day(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    monkeypatch.setattr(updates.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(updates.time, "time", lambda: 100_000.0)
    monkeypatch.setattr(updates, "_latest_version", lambda: "99.0.0")

    updates.notify_if_update_available()
    updates.notify_if_update_available()

    assert capsys.readouterr().err == (
        "Agent Voice 99.0.0 is available; run: agent-voice update\n"
    )
    assert json.loads((tmp_path / "update-check.json").read_text())["latest"] == (
        "99.0.0"
    )


def test_update_notice_skips_noninteractive_use(monkeypatch, capsys):
    monkeypatch.setattr(updates.sys.stderr, "isatty", lambda: False)
    monkeypatch.setattr(
        updates,
        "_latest_version",
        lambda: (_ for _ in ()).throw(AssertionError("network request")),
    )

    updates.notify_if_update_available()

    assert capsys.readouterr().err == ""


def test_update_notice_skips_when_no_console_is_attached(monkeypatch):
    monkeypatch.setattr(updates, "sys", SimpleNamespace(stderr=None))
    monkeypatch.setattr(
        updates,
        "_latest_version",
        lambda: (_ for _ in ()).throw(AssertionError("network request")),
    )

    updates.notify_if_update_available()


def test_run_update_delegates_to_uv(tmp_path, monkeypatch):
    calls = []
    (tmp_path / "uv-receipt.toml").touch()
    monkeypatch.setattr(updates.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(updates.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(
        updates.subprocess,
        "run",
        lambda command, check: (
            calls.append((command, check)) or SimpleNamespace(returncode=0)
        ),
    )

    assert updates.run_update() == 0
    assert calls == [(["/usr/bin/uv", "tool", "upgrade", "agent-voice"], False)]


def test_run_update_delegates_to_pipx(tmp_path, monkeypatch):
    calls = []
    (tmp_path / "pipx_metadata.json").touch()
    monkeypatch.setattr(updates.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(updates.shutil, "which", lambda _name: "/usr/bin/pipx")
    monkeypatch.setattr(
        updates.subprocess,
        "run",
        lambda command, check: (
            calls.append((command, check)) or SimpleNamespace(returncode=0)
        ),
    )

    assert updates.run_update() == 0
    assert calls == [(["/usr/bin/pipx", "upgrade", "agent-voice"], False)]


def test_update_command_runs_without_checking_first(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "run_update", lambda: calls.append("update") or 0)
    monkeypatch.setattr(
        cli,
        "notify_if_update_available",
        lambda: (_ for _ in ()).throw(AssertionError("update check")),
    )

    cli.main(["update"])

    assert calls == ["update"]
