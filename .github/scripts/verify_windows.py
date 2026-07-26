from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

import imageio_ffmpeg

SERVICE_URL = "http://127.0.0.1:18765"


def run_cli(cli: Path, *args: str) -> dict[str, object]:
    completed = subprocess.run(
        [str(cli), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def validate_decodable(path: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    assert "imageio_ffmpeg" in Path(ffmpeg).as_posix()
    completed = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    assert completed.stdout


def validate_wav(path: Path) -> None:
    with wave.open(str(path), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 24_000
        assert audio.getnframes() > 0
    validate_decodable(path)


def validate_mp3(path: Path) -> None:
    assert path.suffix == ".mp3"
    validate_decodable(path)


def check_doctor(report: dict[str, object], service_status: str) -> None:
    assert report["ok"] is True
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["model"]["status"] == "pass"
    assert checks["runtime"]["status"] == "pass"
    assert checks["compressed audio"]["status"] == "pass"
    assert "bundled by imageio-ffmpeg" in checks["compressed audio"]["detail"]
    assert checks["playback"]["status"] in {"pass", "warn"}
    assert "miniaudio" in checks["playback"]["detail"]
    assert checks["service"]["status"] == service_status


def main() -> None:
    if sys.platform != "win32":
        raise RuntimeError("This verification is intentionally Windows-only")
    cli = Path(sys.argv[1]).resolve()
    output_dir = Path(os.environ["RUNNER_TEMP"]) / "agent-voice-windows-e2e"
    output_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run([str(cli), "setup", "--model", "int8"], check=True)
    offline_doctor = run_cli(cli, "doctor", "--service-url", SERVICE_URL, "--json")
    check_doctor(offline_doctor, "warn")

    local_wav = output_dir / "local.wav"
    local = run_cli(
        cli,
        "speak",
        "Windows generation verification.",
        "--service",
        "off",
        "--output",
        str(local_wav),
        "--json",
    )
    assert local["backend"] == "local"
    assert local["played"] is False
    validate_wav(local_wav)

    labeled = run_cli(
        cli,
        "speak",
        "Windows labeled speed verification.",
        "--service",
        "off",
        "--label",
        "Windows E2E",
        "--format",
        "mp3",
        "--speed",
        "1.5",
        "--json",
    )
    labeled_path = Path(str(labeled["path"]))
    assert labeled["backend"] == "local"
    assert labeled["speed"] == 1.5
    assert re.fullmatch(
        r"Windows-E2E-\d{2}-\d{2}-\d{2}-at-\d{2}-\d{2}\.mp3",
        labeled_path.name,
    )
    assert labeled_path.parent == Path(os.environ["AGENT_VOICE_HOME"]) / "recordings"
    validate_mp3(labeled_path)

    log_path = output_dir / "service.log"
    with log_path.open("w", encoding="utf-8") as log:
        service = subprocess.Popen(
            [str(cli), "serve", "--port", "18765"],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            for _ in range(120):
                if service.poll() is not None:
                    raise RuntimeError(f"service exited with {service.returncode}")
                try:
                    with urllib.request.urlopen(
                        f"{SERVICE_URL}/health", timeout=1
                    ) as response:
                        if json.loads(response.read()).get("status") == "ok":
                            break
                except OSError:
                    time.sleep(1)
            else:
                raise RuntimeError("service did not become healthy")

            online_doctor = run_cli(
                cli, "doctor", "--service-url", SERVICE_URL, "--json"
            )
            check_doctor(online_doctor, "pass")

            service_wav = output_dir / "service.wav"
            remote = run_cli(
                cli,
                "speak",
                "Windows localhost service verification.",
                "--service",
                "on",
                "--service-url",
                SERVICE_URL,
                "--output",
                str(service_wav),
                "--json",
            )
            assert remote["backend"] == "service"
            assert remote["played"] is False
            validate_wav(service_wav)
        finally:
            service.terminate()
            try:
                service.wait(timeout=10)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait(timeout=10)
    print(log_path.read_text(encoding="utf-8", errors="replace"))


if __name__ == "__main__":
    main()
