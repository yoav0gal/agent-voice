from __future__ import annotations

import io
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_voice import __version__, cli
from agent_voice.model import (
    LanguageCatalog,
    ModelSelection,
    NamedVoice,
    PreparedArtifact,
    SetupReceipt,
    VoiceCatalog,
)
from agent_voice.speaking import SpeakRequest
from agent_voice.viewer import Viewer


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VOICE_HOME", str(tmp_path / "agent-home"))


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
    assert "printf '%s' \"$TEXT\" | agent-voice speak --format mp3" in help_text
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


@pytest.mark.parametrize("port", ("0", "-1", "65536", "not-a-port"))
def test_serve_rejects_invalid_ports_during_argument_parsing(port, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["serve", "--port", port])

    assert exit_info.value.code == 2
    assert "must be an integer from 1 to 65535" in capsys.readouterr().err


def test_serve_accepts_the_highest_valid_port():
    args = cli.build_parser().parse_args(["serve", "--port", "65535"])

    assert args.port == 65_535


@pytest.mark.parametrize(
    ("command", "public_options"),
    [
        (
            "speak",
            (
                "--markdown",
                "--response-file",
                "--output",
                "--format",
                "--play",
                "--controls",
                "--service",
            ),
        ),
        ("voices", ("--json", "--model-id", "--variant")),
        ("doctor", ("--service-url", "--json")),
        ("serve", ("--host", "--port", "--idle-timeout")),
        ("viewer", ("start", "stop")),
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


def test_viewer_commands_report_start_and_stop(tmp_path, monkeypatch, capsys):
    root = tmp_path / "recordings"
    running = Viewer(root, 49123, 123)
    stopped = Viewer(root)
    monkeypatch.setattr(cli, "resolved_recording_dir", lambda _configured: root)
    monkeypatch.setattr(cli, "ensure_viewer", lambda selected: running)
    monkeypatch.setattr(cli, "stop_viewer", lambda: stopped)

    cli.main(["viewer", "start", "--json"])
    assert json.loads(capsys.readouterr().out) == running.to_dict()
    cli.main(["viewer", "stop", "--json"])
    assert json.loads(capsys.readouterr().out) == stopped.to_dict()


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

    assert default == ModelSelection("kokoro", "int8")
    assert selected == ModelSelection("kokoro", "fp16")
    assert legacy == ModelSelection("kokoro", "full")


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

    assert json.loads(capsys.readouterr().out) == {
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


def test_voices_lists_language_tags_and_keeps_flat_json_voices(monkeypatch, capsys):
    heart = NamedVoice("af_heart")
    emma = NamedVoice("bf_emma")
    catalog = VoiceCatalog(
        named=(heart, emma),
        default=heart,
        accepts_reference_audio=False,
        languages=(
            LanguageCatalog("American English", "en-us", (heart,)),
            LanguageCatalog("British English", "en-gb", (emma,)),
        ),
    )
    monkeypatch.setattr(
        cli, "_model", lambda _args: SimpleNamespace(voice_catalog=lambda: catalog)
    )

    cli.main(["voices"])
    assert capsys.readouterr().out == (
        "American English (en-us)\n  af_heart\n\nBritish English (en-gb)\n  bf_emma\n"
    )

    cli.main(["voices", "--json"])
    assert json.loads(capsys.readouterr().out) == {
        "voices": ["af_heart", "bf_emma"],
        "languages": [
            {"name": "American English", "tag": "en-us", "voices": ["af_heart"]},
            {"name": "British English", "tag": "en-gb", "voices": ["bf_emma"]},
        ],
    }


def test_speak_dispatches_request_and_serializes_receipt(tmp_path, monkeypatch, capsys):
    captured = []
    payload = {"path": str(tmp_path / "recording.wav"), "played": False}

    class Receipt:
        def to_dict(self):
            return payload

    class FakeSpeaker:
        def speak(self, request):
            captured.append(request)
            return Receipt()

    monkeypatch.setattr(cli, "Speaker", FakeSpeaker)
    output = tmp_path / "recording.wav"
    response_file = tmp_path / "response.md"
    response_file.write_text("# Written response", encoding="utf-8")

    cli.main(
        [
            "speak",
            "Visible text.",
            "--response-file",
            str(response_file),
            "--output",
            str(output),
            "--label",
            "ignored",
            "--output-dir",
            str(tmp_path / "managed"),
            "--format",
            "mp3",
            "--voice",
            "bf_emma",
            "--speed",
            "1.15",
            "--lang",
            "en-gb",
            "--play",
            "--controls",
            "--model-id",
            "kokoro",
            "--variant",
            "fp16",
            "--service",
            "timed",
            "--service-timeout",
            "2.5",
            "--service-url",
            "http://127.0.0.1:9000",
        ]
    )

    assert captured == [
        SpeakRequest(
            text="Visible text.",
            selection=ModelSelection("kokoro", "fp16"),
            response_markdown="# Written response",
            output=output,
            label="ignored",
            output_dir=tmp_path / "managed",
            format="mp3",
            voice="bf_emma",
            speed=1.15,
            language="en-gb",
            play=True,
            controls=True,
            service="timed",
            service_timeout_minutes=2.5,
            service_url="http://127.0.0.1:9000",
        )
    ]
    assert json.loads(capsys.readouterr().out) == payload


def test_speak_reads_stdin_and_always_serializes_json(monkeypatch, capsys):
    captured = []

    class Receipt:
        def to_dict(self):
            return {"receipt": True}

    class FakeSpeaker:
        def speak(self, request):
            captured.append(request)
            return Receipt()

    monkeypatch.setattr(cli, "Speaker", FakeSpeaker)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("Text from stdin."))

    cli.main(["speak", "--service", "off"])

    assert captured[0].text == "Text from stdin."
    assert captured[0].service == "off"
    assert json.loads(capsys.readouterr().out) == {"receipt": True}


@pytest.mark.parametrize("positional", (True, False))
def test_speak_accepts_inline_markdown_with_text_or_stdin(
    positional, monkeypatch, capsys
):
    captured = []
    text = "Update. Built successfully with uv."
    markdown = (
        "# Update\n\nBuilt **successfully** with [`uv`](https://docs.astral.sh/uv/)."
    )

    class Receipt:
        def to_dict(self):
            return {"receipt": True}

    class FakeSpeaker:
        def speak(self, request):
            captured.append(request)
            return Receipt()

    monkeypatch.setattr(cli, "Speaker", FakeSpeaker)
    if not positional:
        monkeypatch.setattr(cli.sys, "stdin", io.StringIO(text))

    cli.main(["speak", *([text] if positional else []), "--markdown", markdown])

    assert captured[0].text == text
    assert captured[0].response_markdown == markdown
    assert json.loads(capsys.readouterr().out) == {"receipt": True}


def test_speak_rejects_inline_markdown_with_response_file():
    with pytest.raises(SystemExit) as exit_info:
        cli.build_parser().parse_args(
            [
                "speak",
                "Narration",
                "--markdown",
                "# Response",
                "--response-file",
                "response.md",
            ]
        )

    assert exit_info.value.code == 2


def test_speak_json_flag_is_not_available():
    with pytest.raises(SystemExit) as exit_info:
        cli.build_parser().parse_args(["speak", "Visible text.", "--json"])

    assert exit_info.value.code == 2


def test_speaker_errors_use_cli_error_contract(monkeypatch, capsys):
    class FakeSpeaker:
        def speak(self, request):
            raise ValueError("invalid request")

    monkeypatch.setattr(cli, "Speaker", FakeSpeaker)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["speak", "Visible text."])

    assert exit_info.value.code == 2
    assert capsys.readouterr().err == "Error: invalid request\n"


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


def test_play_command_plays_existing_recording(tmp_path, monkeypatch, capsys):
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
    monkeypatch.setattr(
        cli,
        "play_audio",
        lambda _path: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["play", str(recording)])

    assert exit_info.value.code == 130
    assert capsys.readouterr().err == "Playback stopped\n"


@pytest.mark.parametrize("name", ["missing.mp3", "recording.flac"])
def test_play_command_rejects_missing_or_unsupported_recordings(tmp_path, name, capsys):
    recording = tmp_path / name
    if recording.suffix == ".flac":
        recording.write_bytes(b"audio")

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["play", str(recording)])

    assert exit_info.value.code == 2
    assert "Error:" in capsys.readouterr().err
