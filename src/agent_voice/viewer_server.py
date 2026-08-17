from __future__ import annotations

import argparse
import base64
import errno
import html
import json
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from socketserver import TCPServer
from string import Template
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__
from .audio import PLAYBACK_ACTIONS, PlaybackController, write_audio
from .config import load_defaults
from .media import CONTENT_TYPES
from .model import NamedVoice, SynthesisRequest
from .registry import MODEL_REGISTRY
from .viewer import (
    control_mapping_path,
    delete_expired_recordings,
    language_path,
    player_mapping_path,
    source_path,
    valid_control_token,
    VIEWER_PROTOCOL,
)


DEFAULT_VIEWER_PORT = 8779
_CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, recordings: Path, port: int = 0) -> None:
        self.playback = PlaybackController()
        self._timers: set[threading.Timer] = set()
        self._timer_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), Handler)
        self.recordings = recordings.resolve()
        self.regeneration_lock = threading.Lock()
        self.next_cleanup = time.monotonic()

    def server_close(self) -> None:
        with self._timer_lock:
            for timer in self._timers:
                timer.cancel()
            self._timers.clear()
        self.playback.close()
        super().server_close()

    def schedule_playback(self, recording: Path, delay: float) -> None:
        def start() -> None:
            try:
                self.playback.control(recording, "restart")
            except (OSError, RuntimeError, ValueError):
                pass
            finally:
                with self._timer_lock:
                    self._timers.discard(timer)

        timer = threading.Timer(delay, start)
        timer.daemon = True
        with self._timer_lock:
            self._timers.add(timer)
        timer.start()

    def service_actions(self) -> None:
        now = time.monotonic()
        if now >= self.next_cleanup:
            delete_expired_recordings(self.recordings)
            self.next_cleanup = now + _CLEANUP_INTERVAL_SECONDS

    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves the bind address with getfqdn().
        # The viewer is localhost-only, so avoid a DNS lookup that can block
        # startup on otherwise healthy machines.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    server_version = f"AgentVoiceViewer/{__version__}"

    # ponytail: GET/HEAD are enough for the browser player; add byte ranges only
    # if real recordings prove seeking needs them.
    def do_GET(self) -> None:
        self._get(head=False)

    def do_HEAD(self) -> None:
        self._get(head=True)

    def do_POST(self) -> None:
        server = self.server
        if not isinstance(server, Server) or not self._valid_host(server):
            self.send_error(403)
            return
        url = urlsplit(self.path)
        if url.path.startswith("/play/"):
            self._play(url, server)
            return
        if url.query or self.headers.get("X-Agent-Voice-Control") != "1":
            self.send_error(403)
            return
        target = self._control_target(url.path, server)
        if target is None:
            self.send_error(404)
            return
        recording, action = target
        try:
            state = server.playback.control(recording, action)
        except (OSError, RuntimeError, ValueError):
            self.send_error(503, "Playback control failed")
            return
        self._send(json.dumps(state.to_dict()).encode(), "application/json", False)

    def _play(self, url, server: Server) -> None:
        if self.headers.get("X-Agent-Voice-Playback") != "1":
            self.send_error(403)
            return
        delay = _playback_delay(url.query)
        if delay is None:
            self.send_error(404)
            return
        recording = self._recording(url.path.removeprefix("/play/"), server)
        if recording is None:
            self.send_error(404)
            return
        if delay:
            server.schedule_playback(recording, delay)
            payload = {"state": "scheduled", "starts_in_seconds": delay}
        else:
            try:
                payload = {
                    "state": "started",
                    **server.playback.control(recording, "restart").to_dict(),
                }
            except (OSError, RuntimeError, ValueError):
                self.send_error(503, "Playback could not be started")
                return
        self._send(json.dumps(payload).encode(), "application/json", False)

    def _get(self, *, head: bool) -> None:
        server = self.server
        if not isinstance(server, Server) or not self._valid_host(server):
            self.send_error(403)
            return

        url = urlsplit(self.path)
        if url.query:
            self.send_error(404)
            return
        if url.path == "/health":
            self._send(
                json.dumps(
                    {
                        "service": "agent-voice-viewer",
                        "pid": os.getpid(),
                        "port": server.server_port,
                        "protocol": VIEWER_PROTOCOL,
                    }
                ).encode(),
                "application/json",
                head,
            )
            return

        if url.path.startswith("/control/"):
            self.send_error(405)
            return

        prefix = next(
            (
                value
                for value in ("/recordings/", "/player/")
                if url.path.startswith(value)
            ),
            None,
        )
        encoded = url.path.removeprefix(prefix or "")
        try:
            recording = (
                self._player_recording(encoded, server)
                if prefix == "/player/"
                else self._recording(encoded, server)
            )
        except Exception:
            self.send_error(503, "Recording regeneration failed")
            return
        if prefix is None or recording is None:
            self.send_error(404)
        elif prefix == "/player/":
            self._send(_player(recording), "text/html; charset=utf-8", head)
        else:
            content_type = CONTENT_TYPES[recording.suffix.lower().lstrip(".")]
            if not self._send_file(recording, content_type, head):
                try:
                    recording = self._recording(encoded, server)
                except Exception:
                    self.send_error(503, "Recording regeneration failed")
                    return
                if recording is None or not self._send_file(
                    recording, content_type, head
                ):
                    self.send_error(404)

    def _player_recording(self, encoded: str, server: Server) -> Path | None:
        try:
            name = unquote(encoded, errors="strict")
        except (UnicodeError, ValueError):
            return None
        if not name.endswith(".html"):
            return None
        player_name = name.removesuffix(".html")
        if (
            not player_name
            or "/" in player_name
            or "\\" in player_name
            or Path(player_name).name != player_name
        ):
            return None
        try:
            recording_name = player_mapping_path(
                server.recordings,
                player_name,
            ).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        return self._recording(quote(recording_name, safe=""), server)

    def _control_target(self, path: str, server: Server) -> tuple[Path, str] | None:
        if not path.startswith("/control/"):
            return None
        try:
            token, action = (
                unquote(part, errors="strict")
                for part in path.removeprefix("/control/").split("/")
            )
        except (UnicodeError, ValueError):
            return None
        if not valid_control_token(token) or action not in PLAYBACK_ACTIONS:
            return None
        try:
            recording_name = control_mapping_path(server.recordings, token).read_text(
                encoding="utf-8"
            )
        except (OSError, UnicodeError):
            return None
        recording = self._recording(quote(recording_name, safe=""), server)
        return None if recording is None else (recording, action)

    def _valid_host(self, server: Server) -> bool:
        return self.headers.get("Host", "").lower() in {
            f"127.0.0.1:{server.server_port}",
            f"localhost:{server.server_port}",
        }

    def _recording(self, encoded: str, server: Server) -> Path | None:
        try:
            name = unquote(encoded, errors="strict")
        except (OSError, UnicodeError, ValueError):
            return None
        path = self._recording_path(name, server)
        if path is None:
            return None
        if not path.is_file():
            with server.regeneration_lock:
                if not path.is_file():
                    if not all(
                        metadata.is_file()
                        for metadata in (
                            source_path(path),
                            language_path(path),
                        )
                    ):
                        return None
                    _regenerate_recording(path)
        return path if path.is_file() else None

    def _recording_path(self, name: str, server: Server) -> Path | None:
        try:
            if (
                not name
                or "/" in name
                or "\\" in name
                or Path(name).name != name
                or name.rpartition(".")[2].lower() not in CONTENT_TYPES
            ):
                return None
            path = (server.recordings / name).resolve()
        except (OSError, ValueError):
            return None
        return path if path.parent == server.recordings else None

    def _send_file(self, path: Path, content_type: str, head: bool) -> bool:
        try:
            source = path.open("rb")
        except FileNotFoundError:
            return False
        with source:
            size = os.fstat(source.fileno()).st_size
            requested_range = self.headers.get("Range")
            if requested_range is None:
                self.send_response(200)
                self._headers(size, content_type, accept_ranges=True)
                start = 0
                length = size
            else:
                try:
                    start, end = _byte_range(requested_range, size)
                except ValueError:
                    self.send_response(416)
                    self._headers(
                        0,
                        content_type,
                        accept_ranges=True,
                        content_range=f"bytes */{size}",
                    )
                    return True
                length = end - start + 1
                self.send_response(206)
                self._headers(
                    length,
                    content_type,
                    accept_ranges=True,
                    content_range=f"bytes {start}-{end}/{size}",
                )
            if not head:
                source.seek(start)
                remaining = length
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        return True

    def _send(self, body: bytes, content_type: str, head: bool) -> None:
        self.send_response(200)
        self._headers(len(body), content_type)
        if not head:
            self.wfile.write(body)

    def _headers(
        self,
        length: int,
        content_type: str,
        *,
        accept_ranges: bool = False,
        content_range: str | None = None,
    ) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        if accept_ranges:
            self.send_header("Accept-Ranges", "bytes")
        if content_range is not None:
            self.send_header("Content-Range", content_range)
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

    def log_message(self, message: str, *args: object) -> None:
        return


def serve(recordings: Path, state_file: Path) -> None:
    recordings.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "service": "agent-voice-viewer",
                "pid": os.getpid(),
                "status": "binding",
                "recordings_dir": str(recordings.resolve()),
            }
        ),
        encoding="utf-8",
    )
    server = create_server(recordings)
    state_file.write_text(
        json.dumps(
            {
                "service": "agent-voice-viewer",
                "pid": os.getpid(),
                "status": "ready",
                "port": server.server_port,
                "recordings_dir": str(recordings.resolve()),
            }
        ),
        encoding="utf-8",
    )
    os.chmod(state_file, 0o600)
    server.serve_forever()


def create_server(recordings: Path) -> Server:
    try:
        return Server(recordings, DEFAULT_VIEWER_PORT)
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        return Server(recordings)


def _byte_range(value: str, size: int) -> tuple[int, int]:
    if not value.startswith("bytes=") or "," in value or size <= 0:
        raise ValueError("Unsupported byte range")
    start_text, separator, end_text = value.removeprefix("bytes=").partition("-")
    if not separator:
        raise ValueError("Unsupported byte range")

    if start_text:
        if not start_text.isdigit() or (end_text and not end_text.isdigit()):
            raise ValueError("Unsupported byte range")
        start = int(start_text)
        end = size - 1 if not end_text else min(int(end_text), size - 1)
        if start >= size or end < start:
            raise ValueError("Unsatisfiable byte range")
        return start, end

    if not end_text.isdigit():
        raise ValueError("Unsupported byte range")
    suffix_length = int(end_text)
    if suffix_length <= 0:
        raise ValueError("Unsatisfiable byte range")
    return max(0, size - suffix_length), size - 1


def _playback_delay(query: str) -> float | None:
    if not query:
        return 0.0
    values = parse_qs(query, keep_blank_values=True)
    if set(values) != {"after"} or len(values["after"]) != 1:
        return None
    try:
        delay = float(values["after"][0])
    except ValueError:
        return None
    return delay if math.isfinite(delay) and delay >= 0 else None


def _player(recording: Path) -> bytes:
    name = recording.name
    try:
        response_text = source_path(recording).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        response_text = ""
    template = Template(
        resources.files("agent_voice")
        .joinpath("templates", "recording.html")
        .read_text(encoding="utf-8")
    )
    return template.substitute(
        BRAND_ICON=_image_data_url("brand-icon.svg"),
        PAGE_TITLE=html.escape(f"{name} · Agent Voice", quote=True),
        RECORDING_NAME=html.escape(name, quote=True),
        MEDIA_SOURCE=f"/recordings/{quote(name, safe='')}",
        MEDIA_TYPE=CONTENT_TYPES[recording.suffix.lower().lstrip(".")],
        RESPONSE_TEXT=html.escape(response_text),
    ).encode()


def _regenerate_recording(recording: Path) -> None:
    text = source_path(recording).read_text(encoding="utf-8")
    language = language_path(recording).read_text(encoding="utf-8").strip()
    if not language:
        raise ValueError("Recording language is empty")
    defaults = load_defaults()
    model = MODEL_REGISTRY.create(MODEL_REGISTRY.select())
    speech = model.synthesize(
        SynthesisRequest(
            text=text,
            voice=NamedVoice(defaults.voice),
            speed=defaults.speed,
            language=language,
        )
    )
    write_audio(
        speech.samples,
        speech.sample_rate,
        recording,
        recording.suffix.lower().lstrip("."),
    )


def _image_data_url(name: str) -> str:
    image = resources.files("agent_voice").joinpath("templates", name).read_bytes()
    encoded = base64.b64encode(image).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("recordings", type=Path)
    parser.add_argument("state_file", type=Path)
    args = parser.parse_args()
    serve(args.recordings.resolve(), args.state_file.resolve())


if __name__ == "__main__":
    main()
