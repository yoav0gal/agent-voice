from __future__ import annotations

import json
import re
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from agent_voice import __version__
from agent_voice import cli
from agent_voice.client import ServiceUnavailable
from agent_voice.config import load_defaults, update_defaults


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


def test_speak_help_distinguishes_managed_label_from_exact_output(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["speak", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    normalized_help = " ".join(help_text.split())
    assert "managed filename prefix; ignored when --output is set" in normalized_help
    assert (
        "exact output path; takes precedence over managed output options"
        in normalized_help
    )
    assert (
        "directory for the managed filename; ignored when --output is set"
        in normalized_help
    )


def test_top_level_help_has_a_compact_agent_workflow(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "agent-voice setup" in help_text
    assert "printf '%s' \"$TEXT\" | agent-voice speak --format mp3 --json" in help_text
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


def test_command_help_exposes_agent_relevant_defaults_and_side_effects(capsys):
    for command in ("speak", "voices", "doctor", "serve"):
        with pytest.raises(SystemExit) as exit_info:
            cli.main([command, "--help"])
        assert exit_info.value.code == 0

    help_text = " ".join(capsys.readouterr().out.split())
    assert "output format (default: configured format)" in help_text
    assert "language tag (default: en-us)" in help_text
    assert "one JSON receipt with an absolute output path" in help_text
    assert "successful JSON reports played=true" in help_text
    assert "service mode (default: configured mode)" in help_text
    assert "download the selected model if it is missing" in help_text
    assert "Exit 0 means required checks passed" in help_text
    assert "bind port (default: 8765)" in help_text


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


def test_agent_voice_skill_uses_global_command():
    project = Path(__file__).parents[1]
    skill = (project / "skills/agent-voice/SKILL.md").read_text()
    readme = (project / "README.md").read_text()

    assert "name: agent-voice" in skill
    assert "create a local speech recording" in skill
    assert "read text aloud" in skill
    assert "generate speech audio" in skill
    assert "/Users/" not in skill
    assert "./agent-voice" not in skill
    assert "agent-voice speak" in skill
    assert 'agent-voice speak "Text to record" --json' in skill
    assert 'agent-voice speak "Text to read" --play --json' in skill
    assert "printf '%s' \"$TEXT\" | agent-voice speak --format mp3 --json" in skill
    assert "agent-voice speak --help" in skill
    assert "--play" in skill
    assert "`played` is `true`" in skill
    assert "absolute `path`" in skill
    assert "user supplied or can already see" in skill
    assert "agent-voice voices" not in skill
    assert "agent-voice doctor" not in skill
    assert "agent-voice config" not in skill
    assert "uv tool install" not in skill
    assert "$VISIBLE_SCRIPT" not in skill
    assert "agent-voice serve" not in skill
    assert "--service" not in skill
    assert "Default voice:" not in skill
    assert "Default speed:" not in skill
    assert (
        "npx skills add yoav0gal/agent-voice --skill agent-voice "
        "--global --agent codex --yes"
    ) in readme
    assert "skills/read-aloud" not in readme
    assert "https://skills.sh/b/yoav0gal/agent-voice" in readme


def test_spoken_responses_skill_is_explicit_and_task_scoped():
    project = Path(__file__).parents[1]
    skill = (project / "skills/spoken-responses/SKILL.md").read_text()
    metadata = (project / "skills/spoken-responses/agents/openai.yaml").read_text()
    readme = (project / "README.md").read_text()

    assert "name: spoken-responses" in skill
    assert "Use Agent Voice" in skill
    assert "written answer" in skill
    assert "Codex" not in skill
    assert "/Users/" not in skill
    assert "./agent-voice" not in skill
    assert "agent-voice speak" in skill
    assert "uv tool install agent-voice" in skill
    assert "uv tool upgrade agent-voice" in skill
    assert "agent-voice setup" in skill
    assert "0.5.0 or newer" in skill
    assert "--speed" not in skill
    assert "--format mp3" in skill
    assert "--service" not in skill
    assert '--label "$RECORDING_LABEL"' in skill
    assert "## Naming" in skill
    assert "<title> - SR" in skill
    assert "do not add a lookup solely for naming" in skill
    assert "--label" in skill and "can replace this convention" in skill
    assert "--output" in skill and "takes precedence" in skill
    assert "untrusted filename data" in skill
    assert "never as instructions" in skill
    assert "configured voice and speed" in skill
    assert "every visible word in order" in skill
    assert "never carries into another task" in skill
    assert "Render it" in skill and "before the written response" in skill
    assert "bottom" not in skill
    assert "`played` is `true`" in skill
    assert "allow_implicit_invocation: false" in metadata
    assert "$spoken-responses" in metadata
    assert (
        "npx skills add yoav0gal/agent-voice --skill spoken-responses "
        "--global --agent codex --yes"
    ) in readme


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
    assert path.parent == tmp_path
    assert re.fullmatch(
        r"SR-\d{2}-\d{2}-\d{2}-at-\d{2}-\d{2}\.mp3",
        path.name,
    )
    assert path.suffix == ".mp3"
    assert path.read_bytes() == b"recording"


def test_unlabeled_recording_uses_agent_voice_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_VOICE_RECORDING_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_speak_locally", _local_speech())

    cli.main(["speak", "visible text", "--service", "off", "--json"])

    path = Path(json.loads(capsys.readouterr().out)["path"])
    assert path.name.startswith("agent-voice-")


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
