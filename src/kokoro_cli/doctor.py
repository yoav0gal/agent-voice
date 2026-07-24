from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .client import ServiceUnavailable, health_check
from .models import model_dir, models_ready, recording_dir


def diagnose(variant: str, service_url: str) -> dict[str, object]:
    checks: list[dict[str, str]] = []
    version_ok = (3, 11) <= sys.version_info[:2] < (3, 14)
    _check(
        checks,
        "python",
        "pass" if version_ok else "fail",
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )

    try:
        import kokoro_onnx  # noqa: F401
    except ImportError as error:
        _check(checks, "runtime", "fail", str(error))
    else:
        _check(checks, "runtime", "pass", "kokoro-onnx importable")

    ready = models_ready(variant)
    _check(
        checks,
        "model",
        "pass" if ready else "warn",
        f"{variant} verified in {model_dir()}"
        if ready
        else f"{variant} not ready; run kokoro setup --model {variant}",
    )

    output_directory = recording_dir()
    writable = _directory_is_writable(output_directory)
    _check(
        checks,
        "recordings",
        "pass" if writable else "fail",
        f"{output_directory} is writable"
        if writable
        else f"{output_directory} is not writable",
    )

    ffmpeg = shutil.which("ffmpeg")
    _check(
        checks,
        "compressed audio",
        "pass" if ffmpeg else "warn",
        ffmpeg or "ffmpeg not found; WAV output remains available",
    )
    if sys.platform == "win32":
        player = shutil.which("ffplay")
        detail = (
            f"{player}; Windows playback is experimental and not exercised by CI"
            if player
            else "ffplay not found; generation remains available and Windows playback is experimental"
        )
        _check(checks, "playback", "warn", detail)
    else:
        player = shutil.which("afplay") or shutil.which("ffplay")
        _check(
            checks,
            "playback",
            "pass" if player else "warn",
            player or "no afplay/ffplay found; generation remains available",
        )

    try:
        health = health_check(service_url)
    except (ServiceUnavailable, ValueError) as error:
        _check(checks, "service", "warn", f"optional service unavailable: {error}")
    else:
        _check(
            checks,
            "service",
            "pass",
            f"{service_url} · version {health.get('version', 'unknown')} · model {health.get('variant', 'unknown')}",
        )

    return {
        "ok": all(check["status"] != "fail" for check in checks),
        "version": __version__,
        "checks": checks,
    }


def format_report(report: dict[str, object]) -> str:
    lines = [f"Kokoro CLI {report['version']}"]
    markers = {"pass": "✓", "warn": "!", "fail": "✗"}
    for check in report["checks"]:  # type: ignore[union-attr]
        lines.append(
            f"{markers[check['status']]} {check['name']}: {check['detail']}"  # type: ignore[index]
        )
    lines.append("Ready" if report["ok"] else "Not ready")
    return "\n".join(lines)


def _check(checks: list[dict[str, str]], name: str, status: str, detail: str) -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def _directory_is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(path, os.W_OK)
