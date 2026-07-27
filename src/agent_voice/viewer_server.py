from __future__ import annotations

import argparse
import base64
import errno
import html
import json
import os
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
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
        self.send_response(200)
        self._headers(path.stat().st_size, content_type)
        if not head:
            with path.open("rb") as source:
                shutil.copyfileobj(source, self.wfile)

    def _send(self, body: bytes, content_type: str, head: bool) -> None:
        self.send_response(200)
        self._headers(len(body), content_type)
        if not head:
            self.wfile.write(body)

    def _headers(self, length: int, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

    def log_message(self, message: str, *args: object) -> None:
        return


def serve(recordings: Path, state_file: Path) -> None:
    recordings.mkdir(parents=True, exist_ok=True)
    server = create_server(recordings)
    state_file.write_text(
        json.dumps(
            {
                "service": "agent-voice-viewer",
                "pid": os.getpid(),
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
