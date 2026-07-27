from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_voice import __version__
from agent_voice import cli
from agent_voice.client import ServiceUnavailable
from agent_voice.config import load_defaults, update_defaults
from agent_voice.model import PreparedArtifact, SetupReceipt


def _local_speech(audio: bytes = b"recording", captured: dict | None = None):
    def speak(args, text, destination, audio_format):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(audio)
        if captured is not None:
            captured.update(voice=args.voice, speed=args.speed)
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

    return speak


def test_installed_command_and_parser_use_agent_voice_name():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert project["project"]["scripts"] == {
        "agent-voice": "agent_voice.cli:main",
    }
    assert cli.build_parser().prog == "agent-voice"


def test_release_version_metadata_is_synchronized():
    project_root = Path(__file__).parents[1]
    project = tomllib.loads((project_root / "pyproject.toml").read_text())
    lock = tomllib.loads((project_root / "uv.lock").read_text())
    editable_package = next(
        package for package in lock["package"] if package["name"] == "agent-voice"
    )

    assert project["project"]["version"] == __version__
    assert editable_package["version"] == __version__


def test_top_level_help_has_a_compact_agent_workflow(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "agent-voice setup" in help_text
    assert "printf '%s' \"$TEXT\" | agent-voice speak --format mp3 --json" in help_text
    assert 'agent-voice play "/path/to/recording.mp3"' in help_text
    assert "agent-voice doctor --json" in help_text
    assert (
        "Agent speech: read the JSON path; only report playback when played=true."
        in help_text
    )


def test_service_url_uses_agent_voice_environment_name(monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_SERVICE_URL", "http://127.0.0.1:9002")
    assert (
        cli.build_parser().parse_args(["doctor"]).service_url == "http://127.0.0.1:9002"
    )


@pytest.mark.parametrize(
    ("command", "public_options"),
    [
        ("speak", ("--output", "--format", "--play", "--json", "--service")),
        ("voices", ("--json", "--model-id", "--variant")),
        ("doctor", ("--service-url", "--json")),
        ("serve", ("--host", "--port", "--idle-timeout")),
    ],
)
def test_command_help_exposes_public_options(command, public_options, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main([command, "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert all(option in help_text for option in public_options)


def test_config_help_uses_service_modes_and_timeout_language(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["config", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--service {on,off,timed}" in help_text
    assert "--service-timeout MINUTES" in help_text
    assert "--keep-alive" not in help_text


def test_model_arguments_separate_identity_from_variant():
    parser = cli.build_parser()

    default = cli._model_selection(parser.parse_args(["speak", "hello"]))
    selected = cli._model_selection(
        parser.parse_args(
            [
                "speak",
                "hello",
                "--model-id",
                "kokoro",
                "--variant",
                "fp16",
            ]
        )
    )
    legacy = cli._model_selection(
        parser.parse_args(["speak", "hello", "--model", "full"])
    )

    assert default == cli.ModelSelection("kokoro", "int8")
    assert selected == cli.ModelSelection("kokoro", "fp16")
    assert legacy == cli.ModelSelection("kokoro", "full")


def test_variant_and_legacy_model_alias_cannot_be_combined(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(
            [
                "doctor",
                "--variant",
                "fp16",
                "--model",
                "int8",
            ]
        )

    assert exit_info.value.code == 2
    assert "--model cannot be combined with --variant" in capsys.readouterr().err


def test_models_lists_registered_adapters_as_json(capsys):
    cli.main(["models", "--json"])

    result = json.loads(capsys.readouterr().out)
    assert result == {
        "default_model_id": "kokoro",
        "models": [
            {
                "model_id": "kokoro",
                "display_name": "Kokoro-82M",
                "default_variant": "int8",
                "variants": ["int8", "fp16", "full"],
            }
        ],
    }


def test_label_names_recording_in_default_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_RECORDING_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_speak_locally", _local_speech())

    cli.main(
        [
            "speak",
            "visible text",
            "--label",
            "SR",
            "--format",
            "mp3",
            "--service",
            "off",
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    path = Path(result["path"])
    assert result["file_uri"] == path.as_uri()
    assert set(result["delivery"]) == {"fallback_markdown"}
    assert path.parent == tmp_path
    assert re.fullmatch(
        r"SR-\d{2}-\d{2}-\d{2}-at-\d{2}-\d{2}\.mp3",
        path.name,
    )
    assert path.suffix == ".mp3"
    assert path.read_bytes() == b"recording"
    assert path.with_suffix(".html").is_file()


def test_unlabeled_recording_uses_agent_voice_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_RECORDING_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_speak_locally", _local_speech())

    cli.main(["speak", "visible text", "--service", "off", "--json"])

    result = json.loads(capsys.readouterr().out)
    path = Path(result["path"])
    assert result["file_uri"] == path.as_uri()
    assert path.name.startswith("agent-voice-")
    assert path.suffix == ".mp3"
    assert path.with_suffix(".html").is_file()


def test_json_speak_uses_real_html_delivery(tmp_path, monkeypatch, capsys):
    output = tmp_path / "response notes.mp3"
    monkeypatch.setattr(cli, "_speak_locally", _local_speech())

    cli.main(
        [
            "speak",
            "Every visible word.",
            "--output",
            str(output),
            "--service",
            "off",
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert result["path"] == str(output)
    assert result["file_uri"] == output.as_uri()
    assert set(result["delivery"]) == {"fallback_markdown"}
    player = output.with_suffix(".html")
    lines = result["delivery"]["fallback_markdown"].splitlines()
    assert lines[:5] == [
        "---",
        "",
        "Agent Voice recording response notes.mp3",
        f"Listen: [browser]({player.as_uri()}) · [media]({output.as_uri()})",
        "```sh",
    ]
    assert lines[-3:] == ["```", "", "---"]
    if os.name == "nt":
        assert lines[5] == f"agent-voice play {subprocess.list2cmdline([str(output)])}"
    else:
        assert shlex.split(lines[5]) == ["agent-voice", "play", str(output)]
    assert "Every visible word." in player.read_text()
    assert set(tmp_path.iterdir()) == {output, player}


def test_plain_speak_creates_only_audio(tmp_path, monkeypatch, capsys):
    output = tmp_path / "plain.mp3"
    monkeypatch.setattr(cli, "_speak_locally", _local_speech())
    monkeypatch.setattr(
        cli,
        "prepare_delivery",
        lambda *_args, **_kwargs: pytest.fail(
            "plain speak must not compute delivery metadata"
        ),
    )

    cli.main(
        [
            "speak",
            "Visible text.",
            "--output",
            str(output),
            "--service",
            "off",
        ]
    )

    assert capsys.readouterr().out.startswith(f"Created {output}\n")
    assert set(tmp_path.iterdir()) == {output}


def test_json_speak_keeps_audio_when_player_generation_fails(
    tmp_path, monkeypatch, capsys
):
    output = tmp_path / "fallback.mp3"
    monkeypatch.setattr(cli, "_speak_locally", _local_speech())

    def fail_template():
        raise OSError("template unavailable")

    monkeypatch.setattr("agent_voice.delivery._player_template", fail_template)

    cli.main(
        [
            "speak",
            "Visible text.",
            "--output",
            str(output),
            "--service",
            "off",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert output.read_bytes() == b"recording"
    assert not output.with_suffix(".html").exists()
    assert "[browser]" not in result["delivery"]["fallback_markdown"]
    assert "Could not create HTML player" in captured.err


def test_setup_prepares_model(tmp_path, monkeypatch, capsys):
    model_path = tmp_path / "model.onnx"
    monkeypatch.setattr(
        cli,
        "_model",
        lambda args: SimpleNamespace(
            setup=lambda force=False: SetupReceipt(
                (PreparedArtifact("Ready", model_path),)
            )
        ),
    )

    cli.main(["setup"])

    assert capsys.readouterr().out == f"Ready: {model_path}\n"


def test_play_command_plays_existing_recording(
    tmp_path, monkeypatch, capsys
):
    recording = tmp_path / "existing recording.mp3"
    recording.write_bytes(b"audio")
    calls = []
    monkeypatch.setattr(cli, "play_audio", lambda path: calls.append(path))

    cli.main(["play", str(recording), "--json"])

    assert calls == [recording]
    assert json.loads(capsys.readouterr().out) == {
        "path": str(recording),
        "played": True,
    }


def test_play_command_stops_cleanly_on_keyboard_interrupt(
    tmp_path, monkeypatch, capsys
):
    recording = tmp_path / "recording.mp3"
    recording.write_bytes(b"audio")

    def interrupt(_path):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "play_audio", interrupt)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["play", str(recording)])

    assert exit_info.value.code == 130
    assert capsys.readouterr().err == "Playback stopped\n"


@pytest.mark.parametrize("name", ["missing.mp3", "recording.flac"])
def test_play_command_rejects_missing_or_unsupported_recordings(
    tmp_path, name, capsys
):
    recording = tmp_path / name
    if recording.suffix == ".flac":
        recording.write_bytes(b"audio")

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["play", str(recording)])

    assert exit_info.value.code == 2
    assert "Error:" in capsys.readouterr().err


def test_automatic_recording_name_does_not_overwrite_same_minute_collision(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("AGENT_VOICE_RECORDING_DIR", str(tmp_path))

    class FixedDatetime:
        @staticmethod
        def now():
            return datetime(2026, 7, 26, 10, 13)

    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    existing = tmp_path / "SR-07-26-26-at-10-13.mp3"
    existing.write_bytes(b"existing")
    monkeypatch.setattr(cli, "_speak_locally", _local_speech(b"new recording"))

    cli.main(
        [
            "speak",
            "visible text",
            "--label",
            "SR",
            "--format",
            "mp3",
            "--service",
            "off",
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert Path(result["path"]).name == "SR-07-26-26-at-10-13-2.mp3"
    assert existing.read_bytes() == b"existing"


def test_output_takes_precedence_over_label(tmp_path, monkeypatch, capsys):
    output = tmp_path / "explicit.wav"
    ignored_directory = tmp_path / "ignored"
    monkeypatch.setattr(cli, "_speak_locally", _local_speech(b"explicit recording"))

    cli.main(
        [
            "speak",
            "visible text",
            "--label",
            "!!!",
            "--output",
            str(output),
            "--output-dir",
            str(ignored_directory),
            "--service",
            "off",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert json.loads(captured.out)["path"] == str(output)
    assert "ignoring --label and --output-dir" in captured.err
    assert not ignored_directory.exists()
    assert output.read_bytes() == b"explicit recording"


def test_configured_output_dir_combines_with_label(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    configured = tmp_path / "configured recordings"
    home.mkdir()
    monkeypatch.setenv("AGENT_VOICE_HOME", str(home))
    update_defaults(output_dir=configured)
    monkeypatch.setattr(cli, "_speak_locally", _local_speech(b"configured"))
    cli.main(
        [
            "speak",
            "visible text",
            "--label",
            "Daily update",
            "--service",
            "off",
            "--json",
        ]
    )

    path = Path(json.loads(capsys.readouterr().out)["path"])
    assert path.parent == configured
    assert path.name.startswith("Daily-update-")
    assert path.read_bytes() == b"configured"


def test_output_dir_flag_overrides_environment_and_config(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "home"
    configured = tmp_path / "configured"
    environment = tmp_path / "environment"
    command_line = tmp_path / "command-line"
    home.mkdir()
    monkeypatch.setenv("AGENT_VOICE_HOME", str(home))
    monkeypatch.setenv("AGENT_VOICE_RECORDING_DIR", str(environment))
    update_defaults(output_dir=configured)
    monkeypatch.setattr(cli, "_speak_locally", _local_speech(b"command line"))
    cli.main(
        [
            "speak",
            "visible text",
            "--output-dir",
            str(command_line),
            "--service",
            "off",
            "--json",
        ]
    )

    path = Path(json.loads(capsys.readouterr().out)["path"])
    assert path.parent == command_line
    assert not configured.exists()
    assert not environment.exists()


def test_environment_output_dir_overrides_config(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    configured = tmp_path / "configured"
    environment = tmp_path / "environment"
    home.mkdir()
    monkeypatch.setenv("AGENT_VOICE_HOME", str(home))
    update_defaults(output_dir=configured)
    monkeypatch.setenv("AGENT_VOICE_RECORDING_DIR", str(environment))
    monkeypatch.setattr(cli, "_speak_locally", _local_speech(b"environment"))
    cli.main(["speak", "visible text", "--service", "off", "--json"])

    path = Path(json.loads(capsys.readouterr().out)["path"])
    assert path.parent == environment
    assert not configured.exists()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Review CLI status - SR", "Review-CLI-status-SR"),
        ("  spaced / punctuation  ", "spaced-punctuation"),
        ("A" * 60, "A" * 48),
    ],
)
def test_filename_label_is_portable_and_bounded(value, expected):
    assert cli._filename_label(value) == expected


def test_filename_label_rejects_values_without_ascii_letters_or_numbers():
    with pytest.raises(ValueError, match="at least one ASCII"):
        cli._filename_label("🎙️ ---")


def test_managed_recording_reservations_are_unique_across_threads(
    tmp_path,
):
    def reserve(_):
        return cli._reserve_recording_path("SR", "07-26-26-at-10-13", "mp3", tmp_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(executor.map(reserve, range(8)))

    assert len(set(paths)) == 8
    assert all(path.is_file() for path in paths)


def test_failed_managed_recording_removes_reservation(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_RECORDING_DIR", str(tmp_path))

    def fail(*args, **kwargs):
        raise RuntimeError("generation failed")

    monkeypatch.setattr(cli, "_speak_locally", fail)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(
            [
                "speak",
                "visible text",
                "--label",
                "SR",
                "--service",
                "off",
            ]
        )

    assert exit_info.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_timed_service_falls_back_to_embedded(tmp_path, monkeypatch, capsys):
    output = tmp_path / "fallback.wav"

    def unavailable(*args, **kwargs):
        raise ServiceUnavailable("not running")

    monkeypatch.setattr(cli, "ensure_service", unavailable)
    monkeypatch.setattr(cli, "_speak_locally", _local_speech(b"RIFF-local"))

    cli.main(["speak", "visible text", "-o", str(output), "--json"])

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert "using embedded inference" in captured.err
    assert result["backend"] == "local"
    assert result["service_fallback"] is True
    assert result["played"] is False


def test_timed_service_uses_saved_timeout(tmp_path, monkeypatch, capsys):
    output = tmp_path / "service.wav"
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path / "home"))
    update_defaults(service_timeout_minutes=2.5)
    started = []

    def start(service_url, selection, idle_timeout_minutes):
        started.append((service_url, selection, idle_timeout_minutes))
        return {"status": "ok"}

    def request(
        service_url,
        text,
        destination,
        audio_format,
        voice,
        speed,
        lang,
        *,
        selection,
    ):
        destination.write_bytes(b"RIFF-service")
        return {
            "path": str(destination),
            "format": audio_format,
            "voice": voice,
            "speed": speed,
            "sample_rate": 24_000,
            "duration_seconds": 1.0,
            "generation_seconds": 0.1,
            "backend": "service",
        }

    monkeypatch.setattr(cli, "ensure_service", start)
    monkeypatch.setattr(cli, "request_speech", request)

    cli.main(["speak", "visible text", "-o", str(output), "--json"])

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert started == [
        (
            "http://127.0.0.1:8765",
            cli.ModelSelection("kokoro", "int8"),
            2.5,
        )
    ]
    assert result["backend"] == "service"
    assert "service_fallback" not in result


def test_on_service_starts_without_an_idle_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    update_defaults(service_mode="on")
    started = []

    def unavailable(*args, **kwargs):
        raise ServiceUnavailable("not running")

    monkeypatch.setattr(
        cli,
        "ensure_service",
        lambda service_url, selection, timeout: started.append(timeout),
    )
    monkeypatch.setattr(cli, "request_speech", unavailable)
    monkeypatch.setattr(cli, "_speak_locally", _local_speech(b"RIFF-local"))

    cli.main(["speak", "visible text", "--json"])

    result = json.loads(capsys.readouterr().out)
    assert started == [None]
    assert result["backend"] == "local"
    assert result["service_fallback"] is True


def test_service_timeout_requires_timed_mode(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(
            [
                "speak",
                "visible text",
                "--service",
                "on",
                "--service-timeout",
                "2.5",
            ]
        )
    assert exit_info.value.code == 2


def test_played_is_true_only_after_player_returns(tmp_path, monkeypatch, capsys):
    output = tmp_path / "played.wav"

    played = []
    monkeypatch.setattr(cli, "_speak_locally", _local_speech(b"RIFF-local"))
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
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    update_defaults(voice="bf_emma", speed=1.15)

    monkeypatch.setattr(cli, "_speak_locally", _local_speech(b"RIFF-local", captured))

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


def test_speak_uses_saved_format_and_service_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    update_defaults(
        format="mp3",
        service_mode="off",
    )
    monkeypatch.setattr(
        cli,
        "ensure_service",
        lambda *args, **kwargs: pytest.fail("off mode must not start a service"),
    )
    monkeypatch.setattr(
        cli,
        "request_speech",
        lambda *args, **kwargs: pytest.fail("off mode must not request a service"),
    )
    monkeypatch.setattr(cli, "_speak_locally", _local_speech())

    cli.main(["speak", "visible text", "--json"])

    result = json.loads(capsys.readouterr().out)
    assert result["format"] == "mp3"
    assert Path(result["path"]).suffix == ".mp3"
    assert load_defaults().service.mode == "off"
    assert load_defaults().service.timeout_minutes is None


def test_speak_flags_override_saved_format_and_service(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path))
    update_defaults(format="mp3", service_mode="timed")
    monkeypatch.setattr(cli, "_speak_locally", _local_speech())

    cli.main(
        [
            "speak",
            "visible text",
            "--format",
            "wav",
            "--service",
            "off",
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert result["format"] == "wav"
    assert Path(result["path"]).suffix == ".wav"
