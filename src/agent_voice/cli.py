from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

from . import __version__
from .audio import play_audio
from .client import DEFAULT_SERVICE_URL
from .config import (
    DEFAULT_FORMAT,
    DEFAULT_SERVICE,
    DEFAULT_SERVICE_TIMEOUT_MINUTES,
    FORMATS,
    MAX_SPEED,
    MIN_SPEED,
    SERVICE_MODES,
    config_path,
    load_defaults,
    reset_defaults,
    update_defaults,
)
from .model import ModelSelection, SpeechModel, VoiceCatalog
from .paths import resolved_recording_dir
from .registry import MODEL_REGISTRY
from .speaking import SpeakRequest, Speaker
from .updates import notify_if_update_available, run_update
from .viewer import ensure_viewer, stop_viewer


def build_parser() -> argparse.ArgumentParser:
    default_service_url = os.environ.get("AGENT_VOICE_SERVICE_URL", DEFAULT_SERVICE_URL)
    parser = argparse.ArgumentParser(
        prog="agent-voice",
        description="Create local voice artifacts for AI agents.",
        epilog=(
            "examples:\n"
            "  agent-voice setup\n"
            "  agent-voice controls install\n"
            "  printf '%s' \"$TEXT\" | agent-voice speak --format mp3\n"
            '  agent-voice play "/path/to/recording.mp3"\n'
            "  agent-voice doctor --json\n\n"
            "Agent speech: read the JSON path; only report playback when played=true."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser(
        "setup",
        help="prepare speech assets",
        description="Download and verify the selected speech model.",
    )
    _add_model_arguments(setup)
    setup.add_argument("--force", action="store_true", help="download again")

    subparsers.add_parser(
        "update",
        help="upgrade Agent Voice",
        description="Upgrade Agent Voice through its uv or pipx installer.",
    )

    speak = subparsers.add_parser(
        "speak",
        help="turn text into an audio recording",
        description="Create a local audio recording from positional text or stdin.",
    )
    speak.add_argument("text", nargs="?", help="text to read; omit to read stdin")
    response = speak.add_mutually_exclusive_group()
    response.add_argument(
        "--markdown",
        help="Markdown response to show in the browser viewer",
    )
    response.add_argument(
        "--response-file",
        type=Path,
        help="Markdown response to show in the browser viewer",
    )
    speak.add_argument(
        "-o",
        "--output",
        type=Path,
        help="exact output path; takes precedence over managed output options",
    )
    speak.add_argument(
        "--label",
        help="managed filename prefix; ignored when --output is set",
    )
    speak.add_argument(
        "--output-dir",
        type=Path,
        help="directory for the managed filename; ignored when --output is set",
    )
    speak.add_argument(
        "-f",
        "--format",
        choices=FORMATS,
        help="output format (default: configured format)",
    )
    speak.add_argument("-v", "--voice", help="voice name (default: configured voice)")
    speak.add_argument(
        "--speed",
        type=float,
        help=f"pitch-preserving output speed from {MIN_SPEED} to {MAX_SPEED} (default: configured speed)",
    )
    speak.add_argument("--lang", default="en-us", help="language tag (default: en-us)")
    speak.add_argument(
        "--play",
        action="store_true",
        help="play after generating; successful JSON reports played=true",
    )
    speak.add_argument(
        "--controls",
        action="store_true",
        help="include experimental desktop playback control links",
    )
    _add_model_arguments(speak)
    speak.add_argument(
        "--service",
        choices=SERVICE_MODES,
        help=(
            "service mode (default: configured mode); on leaves the localhost "
            "service running, off uses embedded inference, and timed stops the "
            "service after an idle timeout"
        ),
    )
    speak.add_argument(
        "--service-timeout",
        type=_positive_minutes,
        metavar="MINUTES",
        help="idle minutes in timed service mode (default: configured timeout)",
    )
    speak.add_argument(
        "--service-url",
        default=default_service_url,
        help=f"localhost service base URL (default: {default_service_url})",
    )

    voices = subparsers.add_parser(
        "voices",
        help="list supported languages and voices",
        description="List supported language tags and voices; download the model if missing.",
        epilog='Select one with: agent-voice speak --lang TAG --voice VOICE "Text"',
    )
    voices.add_argument("--json", action="store_true", help="print one JSON result")
    _add_model_arguments(voices)

    models = subparsers.add_parser(
        "models",
        help="list available speech model adapters",
        description="List model identities and variants known to this installation.",
    )
    models.add_argument("--json", action="store_true", help="print one JSON result")

    config = subparsers.add_parser(
        "config",
        help="show or update speech defaults",
        description="Show or update persisted speech defaults.",
    )
    config.add_argument("--voice", help="set the default voice")
    config.add_argument(
        "--speed",
        type=float,
        help=f"set the default output speed from {MIN_SPEED} to {MAX_SPEED}",
    )
    config.add_argument(
        "--format",
        choices=FORMATS,
        default=argparse.SUPPRESS,
        help=f"set the default output format (default: {DEFAULT_FORMAT})",
    )
    config.add_argument(
        "--service",
        choices=SERVICE_MODES,
        default=argparse.SUPPRESS,
        help=f"set the default service mode (default: {DEFAULT_SERVICE})",
    )
    config.add_argument(
        "--service-timeout",
        type=_positive_minutes,
        default=argparse.SUPPRESS,
        metavar="MINUTES",
        help=f"set the timed mode idle timeout (default: {DEFAULT_SERVICE_TIMEOUT_MINUTES:g})",
    )
    config.add_argument(
        "--output-dir",
        type=_configured_output_dir,
        default=argparse.SUPPRESS,
        metavar="DIR|default",
        help="set the managed recording directory; use default to restore it",
    )
    config.add_argument(
        "--reset", action="store_true", help="restore built-in defaults"
    )
    config.add_argument("--json", action="store_true", help="print one JSON result")

    serve_parser = subparsers.add_parser(
        "serve",
        help="start the local HTTP API",
        description="Start the localhost speech API.",
    )
    serve_parser.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost"),
        default="127.0.0.1",
        help="bind host (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port", type=_port, default=8765, help="bind port (default: 8765)"
    )
    _add_model_arguments(serve_parser)
    serve_parser.add_argument(
        "--idle-timeout",
        type=_positive_minutes,
        metavar="MINUTES",
        help="exit after this many idle minutes; omit to keep serving",
    )
    doctor = subparsers.add_parser(
        "doctor",
        help="check local readiness",
        description=(
            "Check readiness. Exit 0 means required checks passed; "
            "optional gaps are warnings."
        ),
    )
    _add_model_arguments(doctor)
    doctor.add_argument(
        "--service-url",
        default=default_service_url,
        help=f"optional localhost service base URL (default: {default_service_url})",
    )
    doctor.add_argument(
        "--json", action="store_true", help="print one JSON readiness report"
    )

    play = subparsers.add_parser(
        "play",
        help="play an existing local recording",
        description="Play a local recording through the default audio output.",
    )
    play.add_argument("recording", type=Path, help="local audio recording")
    play.add_argument(
        "--json",
        action="store_true",
        help="print a receipt after playback completes",
    )

    viewer = subparsers.add_parser(
        "viewer",
        help="manage the lightweight recording viewer",
        description="Start, stop, or inspect the localhost recording viewer.",
    )
    viewer_actions = viewer.add_subparsers(dest="viewer_action", required=True)
    for action in ("start", "stop"):
        action_parser = viewer_actions.add_parser(action)
        action_parser.add_argument(
            "--json",
            action="store_true",
            help="print one machine-readable viewer report",
        )

    controls = subparsers.add_parser(
        "controls",
        help="manage desktop click controls",
        description="Install or remove the Agent Voice link handler.",
    )
    control_actions = controls.add_subparsers(dest="controls_action", required=True)
    install = control_actions.add_parser("install", help="install the link handler")
    install.add_argument(
        "--json", action="store_true", help="print one machine-readable report"
    )
    uninstall = control_actions.add_parser(
        "uninstall", help="remove the installed link handler"
    )
    uninstall.add_argument(
        "--json", action="store_true", help="print one machine-readable report"
    )

    control_url = subparsers.add_parser(
        "control-url",
        help="handle an Agent Voice control link",
        description="Handle one agent-voice:// playback control link.",
    )
    control_url.add_argument("url")
    control_url.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "update":
        notify_if_update_available()
    try:
        if args.command == "setup":
            _setup(args)
        elif args.command == "update":
            return_code = run_update()
            if return_code:
                raise SystemExit(return_code)
        elif args.command == "speak":
            _speak(args)
        elif args.command == "voices":
            catalog = _model(args).voice_catalog()
            print(
                json.dumps(_voice_catalog_payload(catalog))
                if args.json
                else _format_voice_catalog(catalog)
            )
        elif args.command == "models":
            _models(args)
        elif args.command == "config":
            _config(args)
        elif args.command == "serve":
            from .service import serve

            idle_timeout_seconds = (
                None if args.idle_timeout is None else args.idle_timeout * 60
            )
            model = _model(args)
            model.setup()
            serve(model, args.host, args.port, idle_timeout_seconds)
        elif args.command == "doctor":
            from .doctor import diagnose, format_report

            report = diagnose(_model(args), args.service_url)
            print(json.dumps(report) if args.json else format_report(report))
            if not report["ok"]:
                raise SystemExit(1)
        elif args.command == "play":
            _play(args)
        elif args.command == "viewer":
            _viewer(args)
        elif args.command == "controls":
            _controls(args)
        elif args.command == "control-url":
            _control_url(args)
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        if sys.stderr is not None:
            print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


def _voice_catalog_payload(catalog: VoiceCatalog) -> dict[str, object]:
    return {
        "voices": [voice.name for voice in catalog.named],
        "languages": [
            {
                "name": language.name,
                "tag": language.tag,
                "voices": [voice.name for voice in language.voices],
            }
            for language in catalog.languages
        ],
    }


def _format_voice_catalog(catalog: VoiceCatalog) -> str:
    if not catalog.languages:
        return "\n".join(voice.name for voice in catalog.named)
    return "\n\n".join(
        f"{language.name} ({language.tag})\n"
        + "\n".join(f"  {voice.name}" for voice in language.voices)
        for language in catalog.languages
    )


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model-id",
        choices=MODEL_REGISTRY.model_ids,
        default=MODEL_REGISTRY.default_model_id,
        help=f"speech model identity (default: {MODEL_REGISTRY.default_model_id})",
    )
    parser.add_argument(
        "--variant",
        help="model-specific build; omit to use that model's default",
    )
    parser.add_argument(
        "--model",
        dest="legacy_model_variant",
        help="legacy alias for --variant (Kokoro only)",
    )


def _model(args: argparse.Namespace) -> SpeechModel:
    return MODEL_REGISTRY.create(_model_selection(args))


def _model_selection(args: argparse.Namespace) -> ModelSelection:
    legacy_variant = args.legacy_model_variant
    if legacy_variant is not None and args.variant is not None:
        raise ValueError("--model cannot be combined with --variant")
    if legacy_variant is not None and args.model_id != MODEL_REGISTRY.default_model_id:
        raise ValueError("--model is a legacy Kokoro variant alias")
    return MODEL_REGISTRY.select(args.model_id, legacy_variant or args.variant)


def _models(args: argparse.Namespace) -> None:
    records = [
        {
            "model_id": registration.model_id,
            "display_name": registration.display_name,
            "default_variant": registration.default_variant,
            "variants": list(registration.variants),
        }
        for registration in MODEL_REGISTRY.registrations
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "default_model_id": MODEL_REGISTRY.default_model_id,
                    "models": records,
                }
            )
        )
        return
    for record in records:
        default = (
            " (default)"
            if record["model_id"] == MODEL_REGISTRY.default_model_id
            else ""
        )
        print(f"{record['model_id']}{default} · {record['display_name']}")
        print(
            f"  variants: {', '.join(record['variants'])} "
            f"(default: {record['default_variant']})"
        )


def _speak(args: argparse.Namespace) -> None:
    text = args.text if args.text is not None else sys.stdin.read()
    response_markdown = (
        _read_response_file(args.response_file)
        if args.response_file is not None
        else args.markdown
    )
    receipt = Speaker().speak(
        SpeakRequest(
            text=text,
            selection=_model_selection(args),
            response_markdown=response_markdown,
            output=args.output,
            label=args.label,
            output_dir=args.output_dir,
            format=args.format,
            voice=args.voice,
            speed=args.speed,
            language=args.lang,
            play=args.play,
            service=args.service,
            service_timeout_minutes=args.service_timeout,
            service_url=args.service_url,
            controls=args.controls,
        )
    )
    print(json.dumps(receipt.to_dict()))


def _read_response_file(path: Path) -> str:
    try:
        return path.expanduser().read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Could not read response file: {error}") from error


def _config(args: argparse.Namespace) -> None:
    updates: dict[str, object] = {}
    if args.voice is not None:
        updates["voice"] = args.voice
    if args.speed is not None:
        updates["speed"] = args.speed
    if hasattr(args, "format"):
        updates["format"] = args.format
    if hasattr(args, "service"):
        updates["service_mode"] = args.service
    if hasattr(args, "service_timeout"):
        updates["service_timeout_minutes"] = args.service_timeout
    if hasattr(args, "output_dir"):
        updates["output_dir"] = args.output_dir

    if args.reset and updates:
        raise ValueError(
            "--reset cannot be combined with --voice, --speed, --format, "
            "--service, --service-timeout, or --output-dir"
        )
    if args.reset:
        defaults = reset_defaults()
    elif updates:
        defaults = update_defaults(**updates)
    else:
        defaults = load_defaults()

    payload: dict[str, object] = {
        **defaults.to_dict(),
        "source": "config" if config_path().is_file() else "built-in",
        "path": str(config_path()),
    }
    if args.json:
        print(json.dumps(payload))
    else:
        print(f"Voice: {defaults.voice}")
        print(f"Speed: {defaults.speed:g}")
        print(f"Format: {defaults.format}")
        print(f"Service mode: {defaults.service.mode}")
        if defaults.service.timeout_minutes is not None:
            print(f"Service timeout: {defaults.service.timeout_minutes:g} minutes")
        print(f"Output directory: {defaults.output_dir or 'default'}")
        print(f"Source: {payload['source']}")
        print(f"Config: {payload['path']}")


def _setup(args: argparse.Namespace) -> None:
    receipt = _model(args).setup(force=args.force)
    for artifact in receipt.artifacts:
        print(f"{artifact.label}: {artifact.path}")


def _play(args: argparse.Namespace) -> None:
    path = args.recording.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Recording not found: {path}")
    if path.suffix.lower().lstrip(".") not in FORMATS:
        raise ValueError(f"Recording must use one of: {', '.join(FORMATS)}")
    try:
        play_audio(path)
    except KeyboardInterrupt:
        print("Playback stopped", file=sys.stderr)
        raise SystemExit(130) from None
    receipt = {"path": str(path), "played": True}
    if args.json:
        print(json.dumps(receipt))
    else:
        print(f"Played {path}")


def _positive_minutes(value: str) -> float:
    try:
        minutes = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "must be a positive number of minutes"
        ) from error
    if not math.isfinite(minutes) or minutes <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return minutes


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "must be an integer from 1 to 65535"
        ) from error
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("must be an integer from 1 to 65535")
    return port


def _configured_output_dir(value: str) -> Path | None:
    if value.lower() == "default":
        return None
    if not value.strip():
        raise argparse.ArgumentTypeError("must be a directory path or default")
    return Path(value).expanduser().resolve()


def _viewer(args: argparse.Namespace) -> None:
    if args.viewer_action == "stop":
        report = stop_viewer()
    else:
        report = ensure_viewer(resolved_recording_dir(load_defaults().output_dir))

    if args.json:
        print(json.dumps(report.to_dict()))
        return
    if report.running:
        print(f"Recording viewer: {report.url}")
        print(f"Recordings: {report.recordings_dir}")
    else:
        print("Recording viewer: stopped")


def _controls(args: argparse.Namespace) -> None:
    from .controls import handler_path, install_handler, uninstall_handler

    installed = args.controls_action == "install"
    path = install_handler() if installed else handler_path()
    removed = False if installed else uninstall_handler()
    report = {
        "installed": installed,
        "scheme": "agent-voice",
        "path": str(path),
    }
    if not installed:
        report["removed"] = removed
    message = (
        f"Agent Voice controls: {path}"
        if installed
        else f"Agent Voice controls: {'removed' if removed else 'not installed'}"
    )
    print(json.dumps(report) if args.json else message)


def _control_url(args: argparse.Namespace) -> None:
    from .controls import trigger_control_url

    report = trigger_control_url(args.url)
    if args.json:
        print(json.dumps(report))


if __name__ == "__main__":
    main()
