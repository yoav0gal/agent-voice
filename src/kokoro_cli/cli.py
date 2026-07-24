from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .audio import FORMATS, play_audio, write_audio
from .client import (
    DEFAULT_SERVICE_URL,
    ServiceUnavailable,
    health_check,
    request_speech,
)
from .engine import MAX_SPEED, MIN_SPEED, SpeechEngine
from .models import MODEL_ASSETS, download_models, models_ready, recording_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kokoro",
        description="Local Kokoro speech for humans and AI agents.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="download Kokoro model and voices")
    setup.add_argument(
        "--model", choices=MODEL_ASSETS, default="int8", help="model variant"
    )
    setup.add_argument("--force", action="store_true", help="download again")

    speak = subparsers.add_parser("speak", help="turn text into an audio recording")
    speak.add_argument("text", nargs="?", help="text to read; omit to read stdin")
    speak.add_argument("-o", "--output", type=Path, help="output path")
    speak.add_argument("-f", "--format", choices=FORMATS, default="wav")
    speak.add_argument("-v", "--voice", default="af_heart")
    speak.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help=f"speech speed from {MIN_SPEED} to {MAX_SPEED} (default: 1.0)",
    )
    speak.add_argument("--lang", default="en-us")
    speak.add_argument("--play", action="store_true", help="play after generating")
    speak.add_argument(
        "--json", action="store_true", help="print machine-readable result"
    )
    speak.add_argument(
        "--model", choices=MODEL_ASSETS, default="int8", help="model variant"
    )
    speak.add_argument(
        "--service",
        choices=("auto", "required", "off"),
        default="auto",
        help="use a healthy localhost service, require it, or use embedded inference",
    )
    speak.add_argument(
        "--service-url",
        default=os.environ.get("KOKORO_SERVICE_URL", DEFAULT_SERVICE_URL),
        help="localhost service base URL",
    )

    voices = subparsers.add_parser("voices", help="list installed voices")
    voices.add_argument("--json", action="store_true")
    voices.add_argument(
        "--model", choices=MODEL_ASSETS, default="int8", help="model variant"
    )

    serve_parser = subparsers.add_parser("serve", help="start the local HTTP API")
    serve_parser.add_argument(
        "--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1"
    )
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument(
        "--model", choices=MODEL_ASSETS, default="int8", help="model variant"
    )
    doctor = subparsers.add_parser("doctor", help="check local product readiness")
    doctor.add_argument(
        "--model", choices=MODEL_ASSETS, default="int8", help="model variant"
    )
    doctor.add_argument(
        "--service-url",
        default=os.environ.get("KOKORO_SERVICE_URL", DEFAULT_SERVICE_URL),
        help="optional localhost service base URL",
    )
    doctor.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            model, voices = download_models(args.model, args.force)
            print(f"Ready: {model}")
            print(f"Voices: {voices}")
        elif args.command == "speak":
            _speak(args)
        elif args.command == "voices":
            engine = _engine(args.model)
            voices = engine.voices()
            print(json.dumps({"voices": voices}) if args.json else "\n".join(voices))
        elif args.command == "serve":
            from .service import serve

            serve(_engine(args.model), args.host, args.port)
        elif args.command == "doctor":
            from .doctor import diagnose, format_report

            report = diagnose(args.model, args.service_url)
            print(json.dumps(report) if args.json else format_report(report))
            if not report["ok"]:
                raise SystemExit(1)
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


def _engine(variant: str) -> SpeechEngine:
    if not models_ready(variant):
        print("Kokoro model not found; downloading it once...", file=sys.stderr)
        download_models(variant)
    return SpeechEngine(variant)


def _speak(args: argparse.Namespace) -> None:
    text = args.text if args.text is not None else sys.stdin.read()
    audio_format = args.format
    if args.output:
        suffix = args.output.suffix.lower().lstrip(".")
        if suffix:
            if suffix not in FORMATS:
                raise ValueError(
                    f"Output extension must be one of: {', '.join(FORMATS)}"
                )
            audio_format = suffix
        output = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output = recording_dir() / f"kokoro-{timestamp}.{audio_format}"

    fallback_reason: str | None = None
    result: dict[str, object]
    if args.service != "off":
        try:
            health_check(args.service_url)
            result = request_speech(
                args.service_url,
                text,
                output,
                audio_format,
                args.voice,
                args.speed,
                args.lang,
            )
        except ServiceUnavailable as error:
            if args.service == "required":
                raise RuntimeError(
                    f"Required Kokoro service unavailable: {error}"
                ) from error
            fallback_reason = str(error)
            print(
                f"Kokoro service unavailable; using embedded inference ({error})",
                file=sys.stderr,
            )
            result = _speak_locally(args, text, output, audio_format)
    else:
        result = _speak_locally(args, text, output, audio_format)

    path = Path(str(result["path"]))
    if args.play:
        play_audio(path)
    result["played"] = args.play
    if fallback_reason is not None:
        result["service_fallback"] = True
    if args.json:
        print(json.dumps(result))
    else:
        print(f"Created {path}")
        print(
            f"{_display_number(result.get('duration_seconds'))}s audio · {args.voice} · "
            f"{result['backend']} backend"
        )


def _speak_locally(
    args: argparse.Namespace, text: str, output: Path, audio_format: str
) -> dict[str, object]:
    speech = _engine(args.model).synthesize(
        text, voice=args.voice, speed=args.speed, lang=args.lang
    )
    path = write_audio(speech.samples, speech.sample_rate, output, audio_format)
    return {
        "path": str(path),
        "format": audio_format,
        "voice": args.voice,
        "sample_rate": speech.sample_rate,
        "duration_seconds": round(speech.duration_seconds, 3),
        "generation_seconds": round(speech.elapsed_seconds, 3),
        "backend": "local",
    }


def _display_number(value: object) -> str:
    return f"{value:.1f}" if isinstance(value, (int, float)) else "unknown"


if __name__ == "__main__":
    main()
