from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from . import __version__
from .audio import CONTENT_TYPES, FORMATS, play_audio, write_audio
from .config import load_defaults
from .engine import SpeechEngine


@dataclass(frozen=True)
class SpeechRequest:
    text: str
    voice: str
    speed: float
    lang: str
    audio_format: str
    play: bool


def validate_payload(payload: object) -> SpeechRequest:
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    defaults = load_defaults()
    text = payload.get("input", payload.get("text"))
    voice = payload.get("voice", defaults.voice)
    speed = payload.get("speed", defaults.speed)
    lang = payload.get("lang", "en-us")
    audio_format = payload.get("response_format", payload.get("format", "mp3"))
    play = payload.get("play", False)
    if not isinstance(text, str):
        raise ValueError("input must be a string")
    if not isinstance(voice, str) or not voice:
        raise ValueError("voice must be a non-empty string")
    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        raise ValueError("speed must be a number")
    if not isinstance(lang, str) or not lang:
        raise ValueError("lang must be a non-empty string")
    if not isinstance(audio_format, str) or audio_format.lower() not in FORMATS:
        raise ValueError(f"response_format must be one of: {', '.join(FORMATS)}")
    if not isinstance(play, bool):
        raise ValueError("play must be a boolean")
    return SpeechRequest(text, voice, float(speed), lang, audio_format.lower(), play)


class TTSRequestHandler(BaseHTTPRequestHandler):
    engine: SpeechEngine
    max_body_bytes = 100_000
    server_version = f"KokoroCLI/{__version__}"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(30)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(
                200,
                {
                    "status": "ok",
                    "service": "kokoro",
                    "version": __version__,
                    "model": "Kokoro-82M",
                    "variant": self.engine.variant,
                    "ready": True,
                },
            )
        elif self.path == "/voices":
            self._json(200, {"voices": self.engine.voices()})
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path not in ("/speak", "/v1/audio/speech"):
            self._json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > self.max_body_bytes:
                raise ValueError("Request body must be between 1 and 100,000 bytes")
            payload = json.loads(self.rfile.read(length))
            request = validate_payload(payload)
            audio = self._synthesize(request)
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"error": str(error)})
        except Exception as error:
            self._json(500, {"error": str(error)})
        else:
            self.send_response(200)
            data, audio_format, voice, metadata = audio
            self.send_header("Content-Type", CONTENT_TYPES[audio_format])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Kokoro-Voice", voice)
            self.send_header("X-Kokoro-Speed", str(request.speed))
            self.send_header("X-Kokoro-Sample-Rate", str(metadata["sample_rate"]))
            self.send_header("X-Kokoro-Duration", str(metadata["duration_seconds"]))
            self.send_header(
                "X-Kokoro-Generation-Seconds", str(metadata["generation_seconds"])
            )
            self.send_header("X-Kokoro-Played", str(metadata["played"]).lower())
            self.end_headers()
            self.wfile.write(data)

    def _synthesize(
        self, request: SpeechRequest
    ) -> tuple[bytes, str, str, dict[str, object]]:
        speech = self.engine.synthesize(
            request.text, voice=request.voice, speed=request.speed, lang=request.lang
        )

        with tempfile.TemporaryDirectory(prefix="kokoro-service-") as directory:
            path = Path(directory) / f"speech.{request.audio_format}"
            write_audio(speech.samples, speech.sample_rate, path, request.audio_format)
            data = path.read_bytes()
            if request.play:
                play_audio(path)
        return (
            data,
            request.audio_format,
            request.voice,
            {
                "sample_rate": speech.sample_rate,
                "duration_seconds": round(speech.duration_seconds, 3),
                "generation_seconds": round(speech.elapsed_seconds, 3),
                "played": request.play,
            },
        )

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, message: str, *args: object) -> None:
        print(f"[kokoro] {self.address_string()} {message % args}")


def create_server(engine: SpeechEngine, host: str, port: int) -> HTTPServer:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("This personal audio service only binds to localhost")
    handler = type(
        "ConfiguredTTSRequestHandler",
        (TTSRequestHandler,),
        {"engine": engine},
    )
    return HTTPServer((host, port), handler)


def serve(engine: SpeechEngine, host: str, port: int) -> None:
    server = create_server(engine, host, port)
    print(f"Kokoro TTS listening on http://{host}:{port}")
    print("POST /v1/audio/speech · GET /voices · GET /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Kokoro TTS")
    finally:
        server.server_close()
