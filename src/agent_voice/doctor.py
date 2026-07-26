from __future__ import annotations

import os
import sys
from pathlib import Path

from . import __version__
from .audio import inspect_audio_runtime
from .client import ServiceUnavailable, health_check
from .model import SpeechModel
from .paths import recording_dir


def diagnose(model: SpeechModel, service_url: str) -> dict[str, object]:
    checks: list[dict[str, str]] = []
    version_ok = (3, 11) <= sys.version_info[:2] < (3, 14)
    _check(
        checks,
        "python",
        "pass" if version_ok else "fail",
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )

    for model_check in model.status().checks:
        _check(
            checks,
            model_check.name,
            model_check.status,
            model_check.detail,
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

    audio_runtime = inspect_audio_runtime()
    _check(
        checks,
        "compressed audio",
        "pass" if audio_runtime.ffmpeg_error is None else "fail",
        (
            f"FFmpeg {audio_runtime.ffmpeg_version} bundled by imageio-ffmpeg · "
            f"{audio_runtime.ffmpeg_path}"
            if audio_runtime.ffmpeg_error is None
            else audio_runtime.ffmpeg_error or "bundled FFmpeg unavailable"
        ),
    )
    _check(
        checks,
        "playback",
        "pass" if audio_runtime.playback_error is None else "warn",
        (
            f"miniaudio {audio_runtime.miniaudio_version} · "
            f"{audio_runtime.playback_backend}"
            if audio_runtime.playback_error is None
            else (
                f"miniaudio {audio_runtime.miniaudio_version} installed; "
                f"output device unavailable: {audio_runtime.playback_error}"
            )
        ),
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
            (
                f"{service_url} · version {health.get('version', 'unknown')} · "
                f"model {health.get('model_id', health.get('model', 'unknown'))}/"
                f"{health.get('variant', 'unknown')}"
            ),
        )

    return {
        "ok": all(check["status"] != "fail" for check in checks),
        "version": __version__,
        "checks": checks,
    }


def format_report(report: dict[str, object]) -> str:
    lines = [f"Agent Voice {report['version']}"]
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
