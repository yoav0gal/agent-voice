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

import numpy as np

from . import __version__
from .audio import (
    PLAYBACK_SAMPLE_RATE,
    pcm16_bytes,
    play_audio,
    write_audio,
    write_audio_bytes,
)
from .config import FORMATS, load_defaults
from .media import CONTENT_TYPES, generating_audio
from .model import NamedVoice, Speech, SpeechModel, SynthesisRequest
from .paths import (
    pending_generation_path,
    resolved_recording_dir,
    streaming_pcm_path,
)


@dataclass(frozen=True)
class SpeechRequest:
    text: str
    voice: str
    speed: float
    lang: str
    audio_format: str
    play: bool
    background_recording: str | None = None


def _stream_pcm(speech: Speech) -> bytes:
    if speech.sample_rate != PLAYBACK_SAMPLE_RATE:
        raise RuntimeError(f"Streaming requires {PLAYBACK_SAMPLE_RATE} Hz audio")
    return pcm16_bytes(np.asarray(speech.samples, dtype=np.float32).reshape(-1))


def validate_payload(payload: object) -> SpeechRequest:
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    defaults = load_defaults()
    text = payload.get("input")
    voice = payload.get("voice", defaults.voice)
    speed = payload.get("speed", defaults.speed)
    lang = payload.get("lang", "en-us")
    audio_format = payload.get("response_format", defaults.format)
    play = payload.get("play", False)
    background = payload.get("background")
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
    background_recording = None
    if background is not None:
        if not isinstance(background, dict):
            raise ValueError("background must be an object")
        background_recording = background.get("recording_name")
        if not isinstance(background_recording, str) or not background_recording:
            raise ValueError("background.recording_name must be a non-empty string")
        if play:
            raise ValueError("background speech cannot use play")
    return SpeechRequest(
        text,
        voice,
        float(speed),
        lang,
        audio_format.lower(),
        play,
        background_recording,
    )


class TTSRequestHandler(BaseHTTPRequestHandler):
    model: SpeechModel
    max_body_bytes = 1_000_000
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
                    "features": ["streaming"],
                    "recording_root": str(
                        resolved_recording_dir(load_defaults().output_dir).resolve()
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
        if self.path == "/shutdown":
            server = self.server
            if not isinstance(server, IdleHTTPServer):
                self._json(400, {"error": "Service shutdown is unavailable"})
                return
            self._json(200, {"status": "stopping"})
            server.request_stop()
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
                        "service_timeout_minutes": (
                            None
                            if server.idle_timeout_seconds is None
                            else server.idle_timeout_seconds / 60
                        ),
                    },
                )
            return
        if self.path != "/v1/audio/speech":
            self._json(404, {"error": "Not found"})
            return
        try:
            payload = self._read_json()
            request = validate_payload(payload)
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"error": str(error)})
            return
        if request.background_recording is not None:
            try:
                self._generate_in_background(request)
            except ValueError as error:
                self._json(400, {"error": str(error)})
            except Exception as error:
                self._json(500, {"error": str(error)})
            return
        try:
            audio = self._synthesize(request)
        except Exception as error:
            self._json(500, {"error": str(error)})
            return
        self.send_response(200)
        data, audio_format, voice, metadata = audio
        self.send_header("Content-Type", CONTENT_TYPES[audio_format])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Agent-Voice-Voice", voice)
        self.send_header("X-Agent-Voice-Speed", str(request.speed))
        self.send_header("X-Agent-Voice-Sample-Rate", str(metadata["sample_rate"]))
        self.send_header("X-Agent-Voice-Duration", str(metadata["duration_seconds"]))
        self.send_header(
            "X-Agent-Voice-Generation-Seconds",
            str(metadata["generation_seconds"]),
        )
        self.send_header("X-Agent-Voice-Played", str(metadata["played"]).lower())
        self.end_headers()
        self.wfile.write(data)

    def _generate_in_background(self, request: SpeechRequest) -> None:
        destination = self._background_destination(
            request.background_recording, request.audio_format
        )
        pending = pending_generation_path(destination)
        stream_path = streaming_pcm_path(destination)
        response_started = False
        started = time.perf_counter()
        try:
            pending.touch(mode=0o600, exist_ok=False)
            stream_path.touch(mode=0o600, exist_ok=False)
            write_audio_bytes(generating_audio(request.audio_format), destination)
            synthesis_request = SynthesisRequest(
                text=request.text,
                voice=NamedVoice(request.voice),
                speed=request.speed,
                language=request.lang,
            )
            with stream_path.open("ab", buffering=0) as stream:
                chunks = iter(self.model.synthesize_stream(synthesis_request))
                for speech in chunks:
                    chunk = _stream_pcm(speech)
                    if not chunk:
                        continue
                    stream.write(chunk)
                    break
                else:
                    raise RuntimeError("Speech generation returned no audio")
                self._json(202, {"state": "started", "recording": destination.name})
                response_started = True
                for speech in chunks:
                    chunk = _stream_pcm(speech)
                    if chunk:
                        stream.write(chunk)
            samples = np.fromfile(stream_path, dtype="<i2").astype(np.float32)
            samples /= 32_768
            write_audio(
                samples,
                PLAYBACK_SAMPLE_RATE,
                destination,
                request.audio_format,
            )
            self.log_message(
                "background speech completed in %.3fs", time.perf_counter() - started
            )
        except Exception as error:
            destination.unlink(missing_ok=True)
            stream_path.unlink(missing_ok=True)
            if response_started:
                self.log_error("background speech failed: %s", error)
            else:
                raise
        finally:
            pending.unlink(missing_ok=True)

    def _background_destination(
        self, recording_name: str | None, audio_format: str
    ) -> Path:
        if recording_name is None:
            raise ValueError("background recording name is missing")
        name = Path(recording_name)
        root = resolved_recording_dir(load_defaults().output_dir).resolve()
        destination = (root / name).resolve()
        if (
            name.name != recording_name
            or destination.parent != root
            or destination.suffix.lower() != f".{audio_format}"
        ):
            raise ValueError(
                "background recording name must be a managed filename matching "
                "response_format"
            )
        if (
            not destination.is_file()
            or destination.is_symlink()
            or destination.stat().st_size != 0
        ):
            raise ValueError("background recording must be a new managed reservation")
        return destination

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
            raise ValueError(
                f"Request body must be between 1 and {self.max_body_bytes:,} bytes"
            )
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _host_is_local(self) -> bool:
        server = self.server
        if not isinstance(server, IdleHTTPServer):
            return False
        port = server.server_port
        allowed = {
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            f"[::1]:{port}",
        }
        return self.headers.get("Host", "").lower() in allowed

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
        self._stop_requested = threading.Event()

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
        while not self._stop_requested.is_set():
            idle_timeout, active_requests, last_completed = self._activity_snapshot()
            if idle_timeout is None or active_requests:
                self.timeout = 0.5
            else:
                remaining = idle_timeout - (time.monotonic() - last_completed)
                if remaining <= 0:
                    return
                self.timeout = min(0.5, remaining)
            self.handle_request()

    def request_stop(self) -> None:
        self._stop_requested.set()

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
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65_535:
        raise ValueError("Port must be an integer from 0 to 65535")
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


def _recover_interrupted_generations() -> int:
    root = resolved_recording_dir(load_defaults().output_dir).resolve()
    if not root.is_dir():
        return 0
    recovered = 0
    # ponytail: one service owns a managed recording root; add per-job locks if
    # multi-port services ever need to share one root.
    for pending in root.glob(".*.pending"):
        recording = root / pending.name[1 : -len(".pending")]
        audio_format = recording.suffix.lower().lstrip(".")
        if audio_format not in FORMATS:
            continue
        try:
            placeholder = generating_audio(audio_format)
            remove_recording = (
                recording.is_file()
                and not recording.is_symlink()
                and (
                    recording.stat().st_size == 0
                    or (
                        recording.stat().st_size == len(placeholder)
                        and recording.read_bytes() == placeholder
                    )
                )
            )
            if remove_recording:
                recording.unlink()
            streaming_pcm_path(recording).unlink(missing_ok=True)
            pending.unlink()
        except OSError:
            continue
        recovered += 1
    return recovered


def serve(
    model: SpeechModel,
    host: str,
    port: int,
    idle_timeout_seconds: float | None = None,
) -> None:
    server = create_server(model, host, port, idle_timeout_seconds)
    recovered = _recover_interrupted_generations()
    print(f"Agent Voice listening on http://{host}:{server.server_port}")
    if recovered:
        print(f"Recovered {recovered} interrupted generation(s)")
    if idle_timeout_seconds is not None:
        print(f"Stops after {idle_timeout_seconds / 60:g} idle minutes")
    print("POST /v1/audio/speech · GET /voices · GET /health")
    try:
        server.serve_until_idle()
    except KeyboardInterrupt:
        print("\nStopping Agent Voice")
    finally:
        server.server_close()
