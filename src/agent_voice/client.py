from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from filelock import FileLock, Timeout as FileLockTimeout

from .audio import write_audio_bytes
from .model import ModelSelection
from .paths import project_root

DEFAULT_SERVICE_URL = "http://127.0.0.1:8765"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ServiceUnavailable(RuntimeError):
    """Raised when the optional localhost service cannot be used."""


def validate_service_url(service_url: str) -> str:
    url = service_url.rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("Agent Voice service URL must be localhost over http")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("Agent Voice service URL has an invalid port") from error
    if (
        parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Agent Voice service URL cannot include credentials, path, query, or fragment"
        )
    return url


def health_check(service_url: str, timeout: float = 0.75) -> dict[str, object]:
    url = validate_service_url(service_url) + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (
        OSError,
        TimeoutError,
        socket.timeout,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as error:
        raise ServiceUnavailable(f"health check failed: {error}") from error
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "ok"
        or payload.get("service") != "agent-voice"
    ):
        raise ServiceUnavailable("health check returned an invalid response")
    return payload


def ensure_service(
    service_url: str,
    selection: ModelSelection,
    idle_timeout_minutes: float | None,
    startup_timeout: float = 10.0,
) -> dict[str, object]:
    """Start one detached localhost service and wait until it is healthy."""
    url = validate_service_url(service_url)
    parsed = urlparse(url)
    host = parsed.hostname
    if host not in {"127.0.0.1", "localhost"}:
        raise ServiceUnavailable(
            "automatic service startup supports 127.0.0.1 or localhost"
        )
    port = parsed.port or 80

    root = project_root()
    root.mkdir(parents=True, exist_ok=True)
    lock = FileLock(root / "service-start.lock", timeout=startup_timeout)
    try:
        with lock:
            try:
                health = health_check(url, timeout=0.2)
            except ServiceUnavailable:
                pass
            else:
                matched = _require_matching_model(health, selection)
                _configure_service_lifecycle(url, idle_timeout_minutes)
                return matched

            lifecycle = (
                "no idle timeout"
                if idle_timeout_minutes is None
                else f"{idle_timeout_minutes:g} minute idle timeout"
            )
            print(f"Starting Agent Voice service ({lifecycle})...", file=sys.stderr)
            command = [
                sys.executable,
                "-m",
                "agent_voice",
                "serve",
                "--host",
                host,
                "--port",
                str(port),
                "--model-id",
                selection.model_id,
                "--variant",
                str(selection.variant),
            ]
            if idle_timeout_minutes is not None:
                command.extend(["--idle-timeout", str(idle_timeout_minutes)])
            options: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "close_fds": True,
            }
            if os.name == "nt":
                options["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            else:
                options["start_new_session"] = True
            process = subprocess.Popen(command, **options)

            ready = False
            try:
                deadline = time.monotonic() + startup_timeout
                last_error: ServiceUnavailable | None = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise ServiceUnavailable(
                            f"service exited with code {process.returncode}"
                        )
                    try:
                        health = health_check(url, timeout=0.2)
                    except ServiceUnavailable as error:
                        last_error = error
                        time.sleep(0.05)
                    else:
                        matched = _require_matching_model(health, selection)
                        _configure_service_lifecycle(url, idle_timeout_minutes)
                        ready = True
                        return matched
                raise ServiceUnavailable(f"service did not become ready: {last_error}")
            finally:
                if not ready:
                    _terminate_process(process)
    except FileLockTimeout as error:
        raise ServiceUnavailable("timed out waiting to start service") from error


def request_speech(
    service_url: str,
    text: str,
    destination: Path,
    audio_format: str,
    voice: str,
    speed: float,
    lang: str,
    *,
    selection: ModelSelection | None = None,
    timeout: float = 300,
) -> dict[str, object]:
    if selection is not None:
        _require_matching_model(health_check(service_url), selection)
    url = validate_service_url(service_url) + "/v1/audio/speech"
    body = json.dumps(
        {
            "input": text,
            "voice": voice,
            "speed": speed,
            "lang": lang,
            "response_format": audio_format,
            "play": False,
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            headers = response.headers
    except urllib.error.HTTPError as error:
        detail = _http_error_detail(error)
        if 400 <= error.code < 500:
            raise ValueError(
                f"Agent Voice service rejected the request: {detail}"
            ) from error
        raise ServiceUnavailable(f"Agent Voice service failed: {detail}") from error
    except (OSError, TimeoutError, socket.timeout, urllib.error.URLError) as error:
        raise ServiceUnavailable(f"speech request failed: {error}") from error

    path = write_audio_bytes(data, destination)
    response_speed = _number_header(headers.get("X-Agent-Voice-Speed"), float)
    return {
        "path": str(path),
        "format": audio_format,
        "voice": headers.get("X-Agent-Voice-Voice", voice),
        "speed": speed if response_speed is None else response_speed,
        "sample_rate": _number_header(headers.get("X-Agent-Voice-Sample-Rate"), int),
        "duration_seconds": _number_header(
            headers.get("X-Agent-Voice-Duration"), float
        ),
        "generation_seconds": _number_header(
            headers.get("X-Agent-Voice-Generation-Seconds"), float
        ),
        "backend": "service",
    }


def _configure_service_lifecycle(
    service_url: str, idle_timeout_minutes: float | None
) -> None:
    url = validate_service_url(service_url) + "/lifecycle"
    body = json.dumps({"idle_timeout_minutes": idle_timeout_minutes}).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read())
    except (
        OSError,
        TimeoutError,
        socket.timeout,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as error:
        raise ServiceUnavailable(
            f"could not configure service lifecycle: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise ServiceUnavailable("service lifecycle returned an invalid response")


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            return


def _require_matching_model(
    health: dict[str, object], selection: ModelSelection
) -> dict[str, object]:
    actual_model = health.get("model_id")
    actual_variant = health.get("variant")
    if actual_model != selection.model_id or actual_variant != selection.variant:
        raise ServiceUnavailable(
            "localhost model mismatch: "
            f"requested {selection.model_id}/{selection.variant}, "
            f"running {actual_model or 'unknown'}/{actual_variant or 'unknown'}"
        )
    return health


def _http_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read())
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            return payload["error"]
    except (json.JSONDecodeError, OSError):
        pass
    return f"HTTP {error.code}"


def _number_header(
    value: str | None, converter: type[int] | type[float]
) -> int | float | None:
    try:
        return converter(value) if value is not None else None
    except ValueError:
        return None
