from __future__ import annotations

import json

import pytest

from agent_voice import cli
from agent_voice.config import (
    DEFAULT_FORMAT,
    DEFAULT_SERVICE_TIMEOUT_MINUTES,
    DEFAULT_SPEED,
    DEFAULT_VOICE,
    config_path,
    load_defaults,
    reset_defaults,
    update_defaults,
)


def test_built_in_defaults_are_used_without_a_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))

    defaults = load_defaults()

    assert defaults.voice == DEFAULT_VOICE
    assert defaults.speed == DEFAULT_SPEED
    assert defaults.format == DEFAULT_FORMAT
    assert defaults.service_timeout_minutes == DEFAULT_SERVICE_TIMEOUT_MINUTES
    assert defaults.output_dir is None
    assert not config_path().exists()


def test_defaults_are_persisted_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))

    update_defaults(voice="bf_emma", speed=1.15)

    assert load_defaults().voice == "bf_emma"
    assert load_defaults().speed == 1.15
    assert json.loads(config_path().read_text()) == {
        "voice": "bf_emma",
        "speed": 1.15,
        "format": "mp3",
        "service": {
            "timeout_minutes": 10.0,
        },
        "output_dir": None,
        "viewer_base_url": None,
    }

    reset_defaults()
    assert load_defaults().voice == DEFAULT_VOICE
    assert load_defaults().format == DEFAULT_FORMAT
    assert load_defaults().service_timeout_minutes == 10.0
    assert load_defaults().output_dir is None
    assert not config_path().exists()


@pytest.mark.parametrize("speed", [0.49, 4.01])
def test_invalid_default_speed_is_rejected(tmp_path, monkeypatch, speed):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))

    with pytest.raises(ValueError, match="between 0.5 and 4.0"):
        update_defaults(speed=speed)


def test_service_timeout_is_changeable(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))

    update_defaults(service_timeout_minutes=2.5)
    assert load_defaults().service_timeout_minutes == 2.5
    assert json.loads(config_path().read_text())["service"] == {
        "timeout_minutes": 2.5,
    }


@pytest.mark.parametrize("minutes", [0, -1, True, "ten", float("nan"), float("inf")])
def test_invalid_service_timeout_is_rejected(tmp_path, monkeypatch, minutes):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))

    with pytest.raises(ValueError, match="Service timeout"):
        update_defaults(service_timeout_minutes=minutes)


def test_existing_config_inherits_new_service_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    config_path().write_text('{"voice": "bf_emma", "speed": 1.15}')

    assert load_defaults().service_timeout_minutes == 10.0
    assert load_defaults().format == "mp3"
    assert load_defaults().output_dir is None


def test_legacy_service_mode_is_ignored_but_its_timeout_is_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    config_path().write_text('{"service": {"mode": "timed", "timeout_minutes": 3.5}}')

    assert load_defaults().service_timeout_minutes == 3.5


def test_invalid_format_default_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))

    with pytest.raises(ValueError, match="format"):
        update_defaults(format="flac")


def test_output_dir_is_changeable_and_can_restore_default(tmp_path, monkeypatch):
    home = tmp_path / "home"
    output = tmp_path / "managed recordings"
    home.mkdir()
    monkeypatch.setenv("AGENT_VOICE_HOME", str(home))

    update_defaults(output_dir=output)
    assert load_defaults().output_dir == str(output.resolve())

    update_defaults(output_dir=None)
    assert load_defaults().output_dir is None


def test_output_dir_rejects_an_existing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    output = tmp_path / "not-a-directory"
    output.write_text("file")

    with pytest.raises(ValueError, match="not a directory"):
        update_defaults(output_dir=output)


def test_config_command_updates_and_reports_defaults(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))

    cli.main(
        [
            "config",
            "--voice",
            "bf_emma",
            "--speed",
            "1.2",
            "--format",
            "mp3",
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert result["voice"] == "bf_emma"
    assert result["speed"] == 1.2
    assert result["format"] == "mp3"
    assert result["service"] == {"timeout_minutes": 10.0}
    assert result["output_dir"] is None
    assert result["source"] == "config"
    assert result["path"] == str(tmp_path / "config.json")


def test_config_command_sets_service_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))

    cli.main(["config", "--service-timeout", "3.5", "--json"])
    assert json.loads(capsys.readouterr().out)["service"] == {
        "timeout_minutes": 3.5,
    }


def test_config_command_sets_and_resets_output_dir(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    output = tmp_path / "recordings"
    home.mkdir()
    monkeypatch.setenv("AGENT_VOICE_HOME", str(home))

    cli.main(["config", "--output-dir", str(output), "--json"])
    assert json.loads(capsys.readouterr().out)["output_dir"] == str(output.resolve())

    cli.main(["config", "--output-dir", "default", "--json"])
    assert json.loads(capsys.readouterr().out)["output_dir"] is None


def test_config_sets_and_clears_remote_viewer_origin(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    cli.main(["config", "--viewer-base-url", "https://Mini.example:8443/", "--json"])
    assert (
        json.loads(capsys.readouterr().out)["viewer_base_url"]
        == "https://mini.example:8443"
    )
    assert load_defaults().viewer_base_url == "https://mini.example:8443"
    update_defaults(speed=1.2)
    assert load_defaults().viewer_base_url == "https://mini.example:8443"

    cli.main(["config", "--viewer-base-url", "default", "--json"])
    assert json.loads(capsys.readouterr().out)["viewer_base_url"] is None


@pytest.mark.parametrize(
    "url",
    [
        "http://mini.example",
        "https://",
        "https://user:secret@mini.example",
        "https://mini.example/voice",
        "https://mini.example?x=1",
        "https://mini.example#player",
        "https://mini.example:0",
        "https://mini.example:65536",
        "https://mini.example:bad",
        "https://mini.example\n",
        "https://mini.example\\attacker",
        "https://*.example",
    ],
)
def test_invalid_viewer_origin_does_not_change_config(tmp_path, monkeypatch, url):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="Viewer base URL"):
        update_defaults(viewer_base_url=url)
    assert not config_path().exists()


@pytest.mark.parametrize(
    "update",
    [
        ["--voice", "bf_emma"],
        ["--speed", "1.2"],
        ["--format", "mp3"],
        ["--service-timeout", "3.5"],
        ["--output-dir", "default"],
        ["--viewer-base-url", "default"],
    ],
)
def test_config_reset_rejects_updates(update):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["config", "--reset", *update])

    assert exit_info.value.code == 2
