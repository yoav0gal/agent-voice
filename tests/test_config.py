from __future__ import annotations

import json

import pytest

from kokoro_cli import cli
from kokoro_cli.config import (
    DEFAULT_SPEED,
    DEFAULT_VOICE,
    config_path,
    load_defaults,
    reset_defaults,
    update_defaults,
)


def test_built_in_defaults_are_used_without_a_config(tmp_path, monkeypatch):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path))

    defaults = load_defaults()

    assert defaults.voice == DEFAULT_VOICE
    assert defaults.speed == DEFAULT_SPEED
    assert not config_path().exists()


def test_defaults_are_persisted_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path))

    update_defaults(voice="bf_emma", speed=1.15)

    assert load_defaults().voice == "bf_emma"
    assert load_defaults().speed == 1.15
    assert json.loads(config_path().read_text()) == {
        "voice": "bf_emma",
        "speed": 1.15,
    }

    reset_defaults()
    assert load_defaults().voice == DEFAULT_VOICE
    assert not config_path().exists()


@pytest.mark.parametrize("speed", [0.49, 4.01])
def test_invalid_default_speed_is_rejected(tmp_path, monkeypatch, speed):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path))

    with pytest.raises(ValueError, match="between 0.5 and 4.0"):
        update_defaults(speed=speed)


def test_config_command_updates_and_reports_defaults(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path))

    cli.main(["config", "--voice", "bf_emma", "--speed", "1.2", "--json"])

    result = json.loads(capsys.readouterr().out)
    assert result["voice"] == "bf_emma"
    assert result["speed"] == 1.2
    assert result["source"] == "config"
    assert result["path"] == str(tmp_path / "config.json")
