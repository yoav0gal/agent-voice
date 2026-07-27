from __future__ import annotations

import json
import math
import socket
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import __version__
from .audio import CONTENT_TYPES, play_audio, write_audio
from .client import LOCAL_HOSTS
from .config import FORMATS, load_defaults
from .model import NamedVoice, SpeechModel, SynthesisRequest


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
    audio_format = payload.get(
        "response_format", payload.get("format", defaults.format)
    )
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
    model: SpeechModel
    max_body_bytes = 100_000
    server_version = f"AgentVoice/{__version__}"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(30)

    def do_GET(self) -> None:
        if not self._host_is_local():
            self._json(403, {"error": "Host must be localhost"})
            return
        if self.path == "/health":
            descriptor = self.model.descriptor
            server = self.server
            idle_timeout_minutes = (
                server.idle_timeout_seconds / 60
                if isinstance(server, IdleHTTPServer)
                and server.idle_timeout_seconds is not None
                else None
            )
            self._json(
                200,
                {
                    "status": "ok",
                    "service": "agent-voice",
                    "version": __version__,
                    "engine": descriptor.runtime,
                    "model": descriptor.display_name,
                    "model_id": descriptor.selection.model_id,
                    "variant": descriptor.selection.variant,
                    "ready": True,
                    "service_mode": (
                        "timed" if idle_timeout_minutes is not None else "on"
                    ),
                    "service_timeout_minutes": idle_timeout_minutes,
                },
            )
        elif self.path == "/voices":
            catalog = self.model.voice_catalog()
            self._json(200, {"voices": [voice.name for voice in catalog.named]})
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if not self._host_is_local():
            self._json(403, {"error": "Host must be localhost"})
            return
        if self.path == "/lifecycle":
            try:
                payload = self._read_json()
                idle_timeout_minutes = payload.get("idle_timeout_minutes")
                server = self.server
                if not isinstance(server, IdleHTTPServer):
                    raise ValueError("Service lifecycle is unavailable")
                server.set_idle_timeout_minutes(idle_timeout_minutes)
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)})
            else:
                self._json(
                    200,
                    {
                        "status": "ok",
                        "service_mode": (
                            "timed" if server.idle_timeout_seconds is not None else "on"
                        ),
                        "service_timeout_minutes": (
                            None
                            if server.idle_timeout_seconds is None
                            else server.idle_timeout_seconds / 60
                        ),
                    },
                )
            return
        if self.path not in ("/speak", "/v1/audio/speech"):
            self._json(404, {"error": "Not found"})
            return
        try:
            payload = self._read_json()
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
            self.send_header("X-Agent-Voice-Voice", voice)
            self.send_header("X-Agent-Voice-Speed", str(request.speed))
            self.send_header("X-Agent-Voice-Sample-Rate", str(metadata["sample_rate"]))
            self.send_header(
                "X-Agent-Voice-Duration", str(metadata["duration_seconds"])
            )
            self.send_header(
                "X-Agent-Voice-Generation-Seconds",
                str(metadata["generation_seconds"]),
            )
            self.send_header("X-Agent-Voice-Played", str(metadata["played"]).lower())
            self.end_headers()
            self.wfile.write(data)

    def _synthesize(
        self, request: SpeechRequest
    ) -> tuple[bytes, str, str, dict[str, object]]:
        speech = self.model.synthesize(
            SynthesisRequest(
                text=request.text,
                voice=NamedVoice(request.voice),
                speed=request.speed,
                language=request.lang,
            )
        )

        with tempfile.TemporaryDirectory(prefix="agent-voice-service-") as directory:
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

    def _read_json(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.partition(";")[0].strip().lower() != "application/json":
            raise ValueError("Content-Type must be application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > self.max_body_bytes:
            raise ValueError("Request body must be between 1 and 100,000 bytes")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _host_is_local(self) -> bool:
        raw_host = self.headers.get("Host", "")
        try:
            parsed = urlsplit(f"//{raw_host}")
            port = parsed.port
        except ValueError:
            return False
        server = self.server
        return (
            isinstance(server, IdleHTTPServer)
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and parsed.hostname in LOCAL_HOSTS
            and port == server.server_port
        )

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, message: str, *args: object) -> None:
        print(f"[agent-voice] {self.address_string()} {message % args}")


class IdleHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        idle_timeout_seconds: float | None,
    ) -> None:
        super().__init__(server_address, handler)
        self.idle_timeout_seconds = idle_timeout_seconds
        self.last_request_completed = time.monotonic()
        self._active_requests = 0
        self._activity_lock = threading.Lock()

    def process_request(
        self, request: socket.socket, client_address: tuple[str, int]
    ) -> None:
        self._mark_request_started()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._mark_request_complete()
            raise

    def process_request_thread(
        self, request: socket.socket, client_address: tuple[str, int]
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._mark_request_complete()

    def set_idle_timeout_minutes(self, minutes: object) -> None:
        if minutes is None:
            with self._activity_lock:
                self.idle_timeout_seconds = None
            return
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)):
            raise ValueError("Idle timeout must be a number of minutes or null")
        value = float(minutes)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Idle timeout must be a finite number greater than zero")
        with self._activity_lock:
            self.idle_timeout_seconds = value * 60

    def serve_until_idle(self) -> None:
        while True:
            idle_timeout, active_requests, last_completed = self._activity_snapshot()
            if idle_timeout is None or active_requests:
                self.timeout = 0.5
            else:
                remaining = idle_timeout - (time.monotonic() - last_completed)
                if remaining <= 0:
                    return
                self.timeout = min(0.5, remaining)
            self.handle_request()

    def _mark_request_started(self) -> None:
        with self._activity_lock:
            self._active_requests += 1

    def _mark_request_complete(self) -> None:
        with self._activity_lock:
            self._active_requests -= 1
            self.last_request_completed = time.monotonic()

    def _activity_snapshot(self) -> tuple[float | None, int, float]:
        with self._activity_lock:
            return (
                self.idle_timeout_seconds,
                self._active_requests,
                self.last_request_completed,
            )

def create_server(
    model: SpeechModel,
    host: str,
    port: int,
    idle_timeout_seconds: float | None = None,
) -> IdleHTTPServer:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("This personal audio service only binds to localhost")
    if idle_timeout_seconds is not None and (
        not math.isfinite(idle_timeout_seconds) or idle_timeout_seconds <= 0
    ):
        raise ValueError("Idle timeout must be a finite number greater than zero")
    handler = type(
        "ConfiguredTTSRequestHandler",
        (TTSRequestHandler,),
        {"model": model},
    )
    return IdleHTTPServer((host, port), handler, idle_timeout_seconds)


def serve(
    model: SpeechModel,
    host: str,
    port: int,
    idle_timeout_seconds: float | None = None,
) -> None:
    server = create_server(model, host, port, idle_timeout_seconds)
    print(f"Agent Voice listening on http://{host}:{port}")
    if idle_timeout_seconds is not None:
        print(f"Stops after {idle_timeout_seconds / 60:g} idle minutes")
    print("POST /v1/audio/speech · GET /voices · GET /health")
    try:
        server.serve_until_idle()
    except KeyboardInterrupt:
        print("\nStopping Agent Voice")
    finally:
        server.server_close()
