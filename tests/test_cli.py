from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from kokoro_cli import cli
from kokoro_cli.client import ServiceUnavailable
from kokoro_cli.config import update_defaults


def test_installed_command_and_parser_use_kokoro_name():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert project["project"]["scripts"] == {"kokoro": "kokoro_cli.cli:main"}
    assert cli.build_parser().prog == "kokoro"


def test_standalone_skill_uses_global_command():
    project = Path(__file__).parents[1]
    skill = (project / "skills/read-aloud/SKILL.md").read_text()
    manifest = json.loads((project / "integrations/ygent.json").read_text())

    assert "name: read-aloud" in skill
    assert not (project / "skills/kokoro-speak").exists()
    assert "/Users/" not in skill
    assert "./kokoro" not in skill
    assert "kokoro speak" in skill
    assert manifest["entrypoint"] == "kokoro"


def test_auto_service_falls_back_to_embedded(tmp_path, monkeypatch, capsys):
    output = tmp_path / "fallback.wav"

    def unavailable(*args, **kwargs):
        raise ServiceUnavailable("not running")

    def speak_locally(args, text, destination, audio_format):
        destination.write_bytes(b"RIFF-local")
        return {
            "path": str(destination),
            "format": audio_format,
            "voice": args.voice,
            "speed": args.speed,
            "sample_rate": 24_000,
            "duration_seconds": 1.0,
            "generation_seconds": 0.1,
            "backend": "local",
        }

    monkeypatch.setattr(cli, "health_check", unavailable)
    monkeypatch.setattr(cli, "_speak_locally", speak_locally)

    cli.main(["speak", "visible text", "-o", str(output), "--json"])

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert "using embedded inference" in captured.err
    assert result["backend"] == "local"
    assert result["service_fallback"] is True
    assert result["played"] is False


def test_required_service_does_not_fall_back(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ServiceUnavailable("not running")

    monkeypatch.setattr(cli, "health_check", unavailable)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(
            [
                "speak",
                "visible text",
                "-o",
                str(tmp_path / "required.wav"),
                "--service",
                "required",
            ]
        )
    assert exit_info.value.code == 2


def test_played_is_true_only_after_player_returns(tmp_path, monkeypatch, capsys):
    output = tmp_path / "played.wav"

    def speak_locally(args, text, destination, audio_format):
        destination.write_bytes(b"RIFF-local")
        return {
            "path": str(destination),
            "format": audio_format,
            "voice": args.voice,
            "speed": args.speed,
            "sample_rate": 24_000,
            "duration_seconds": 1.0,
            "generation_seconds": 0.1,
            "backend": "local",
        }

    played = []
    monkeypatch.setattr(cli, "_speak_locally", speak_locally)
    monkeypatch.setattr(cli, "play_audio", lambda path: played.append(path))

    cli.main(
        [
            "speak",
            "visible text",
            "-o",
            str(output),
            "--service",
            "off",
            "--play",
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert played == [output]
    assert result["played"] is True


def test_speak_uses_saved_defaults(tmp_path, monkeypatch, capsys):
    output = tmp_path / "configured.wav"
    captured = {}
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path))
    update_defaults(voice="bf_emma", speed=1.15)

    def speak_locally(args, text, destination, audio_format):
        captured.update(voice=args.voice, speed=args.speed)
        destination.write_bytes(b"RIFF-local")
        return {
            "path": str(destination),
            "format": audio_format,
            "voice": args.voice,
            "speed": args.speed,
            "sample_rate": 24_000,
            "duration_seconds": 1.0,
            "generation_seconds": 0.1,
            "backend": "local",
        }

    monkeypatch.setattr(cli, "_speak_locally", speak_locally)

    cli.main(
        [
            "speak",
            "visible text",
            "--service",
            "off",
            "--output",
            str(output),
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert captured == {"voice": "bf_emma", "speed": 1.15}
    assert result["voice"] == "bf_emma"
    assert result["speed"] == 1.15
