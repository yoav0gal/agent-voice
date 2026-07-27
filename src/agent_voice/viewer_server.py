from __future__ import annotations

import argparse
import base64
import errno
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from socketserver import TCPServer
from string import Template
from urllib.parse import quote, unquote, urlsplit

from . import __version__
from .media import CONTENT_TYPES
from .viewer import player_mapping_path, transcript_path


DEFAULT_VIEWER_PORT = 8779


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, recordings: Path, port: int = 0) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.recordings = recordings.resolve()

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

    def _get(self, *, head: bool) -> None:
        server = self.server
        if not isinstance(server, Server) or self.headers.get("Host", "").lower() not in {
            f"127.0.0.1:{server.server_port}",
            f"localhost:{server.server_port}",
        }:
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
                    }
                ).encode(),
                "application/json",
                head,
            )
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
        recording = (
            self._player_recording(encoded, server)
            if prefix == "/player/"
            else self._recording(encoded, server)
        )
        if prefix is None or recording is None:
            self.send_error(404)
        elif prefix == "/player/":
            self._send(_player(recording), "text/html; charset=utf-8", head)
        else:
            self._send_file(
                recording,
                CONTENT_TYPES[recording.suffix.lower().lstrip(".")],
                head,
            )

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

    def _recording(self, encoded: str, server: Server) -> Path | None:
        try:
            name = unquote(encoded, errors="strict")
            if (
                not name
                or "/" in name
                or "\\" in name
                or Path(name).name != name
                or name.rpartition(".")[2].lower() not in CONTENT_TYPES
            ):
                return None
            path = (server.recordings / name).resolve(strict=True)
        except (OSError, UnicodeError, ValueError):
            return None
        return (
            path
            if path.parent == server.recordings and path.is_file()
            else None
        )

    def _send_file(self, path: Path, content_type: str, head: bool) -> None:
        size = path.stat().st_size
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
                return
            length = end - start + 1
            self.send_response(206)
            self._headers(
                length,
                content_type,
                accept_ranges=True,
                content_range=f"bytes {start}-{end}/{size}",
            )
        if not head:
            with path.open("rb") as source:
                source.seek(start)
                remaining = length
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

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
        )
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
        )
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


def _player(recording: Path) -> bytes:
    name = recording.name
    try:
        response_text = transcript_path(recording).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        response_text = ""
    template = Template(
        resources.files("agent_voice")
        .joinpath("templates", "recording.html")
        .read_text(encoding="utf-8")
    )
    return template.substitute(
        BRAND_ICON=_image_data_url("brand-icon.svg"),
        BRAND_LOGO=_image_data_url("brand-logo.svg"),
        PAGE_TITLE=html.escape(f"{name} · Agent Voice", quote=True),
        RECORDING_NAME=html.escape(name, quote=True),
        MEDIA_SOURCE=f"/recordings/{quote(name, safe='')}",
        MEDIA_TYPE=CONTENT_TYPES[recording.suffix.lower().lstrip(".")],
        RESPONSE_TEXT=html.escape(response_text),
    ).encode()


def _image_data_url(name: str) -> str:
    image = (
        resources.files("agent_voice")
        .joinpath("templates", name)
        .read_bytes()
    )
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
