from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .audio import write_audio_bytes

DEFAULT_SERVICE_URL = "http://127.0.0.1:8765"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ServiceUnavailable(RuntimeError):
    """Raised when the optional localhost service cannot be used."""


def validate_service_url(service_url: str) -> str:
    url = service_url.rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("Kokoro service URL must be localhost over http")
    if (
        parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Kokoro service URL cannot include credentials, path, query, or fragment"
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
        or payload.get("service") != "kokoro"
    ):
        raise ServiceUnavailable("health check returned an invalid response")
    return payload


def request_speech(
    service_url: str,
    text: str,
    destination: Path,
    audio_format: str,
    voice: str,
    speed: float,
    lang: str,
    timeout: float = 300,
) -> dict[str, object]:
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
                f"Kokoro service rejected the request: {detail}"
            ) from error
        raise ServiceUnavailable(f"Kokoro service failed: {detail}") from error
    except (OSError, TimeoutError, socket.timeout, urllib.error.URLError) as error:
        raise ServiceUnavailable(f"speech request failed: {error}") from error

    path = write_audio_bytes(data, destination)
    return {
        "path": str(path),
        "format": audio_format,
        "voice": headers.get("X-Kokoro-Voice", voice),
        "sample_rate": _number_header(headers.get("X-Kokoro-Sample-Rate"), int),
        "duration_seconds": _number_header(headers.get("X-Kokoro-Duration"), float),
        "generation_seconds": _number_header(
            headers.get("X-Kokoro-Generation-Seconds"), float
        ),
        "backend": "service",
    }


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
