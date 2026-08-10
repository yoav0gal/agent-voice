from __future__ import annotations

import json
import os
import platform
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


def verify_controls(cli: Path, system: str, output_dir: Path) -> None:
    if system not in {"Linux", "Windows"}:
        return
    if system == "Linux":
        os.environ["XDG_DATA_HOME"] = str(output_dir / "xdg-data")
        os.environ["XDG_CONFIG_HOME"] = str(output_dir / "xdg-config")

    installed = run_cli(cli, "controls", "install", "--json")
    assert installed["installed"] is True
    assert installed["scheme"] == "agent-voice"
    if system == "Linux":
        desktop = Path(str(installed["path"]))
        contents = desktop.read_text(encoding="utf-8")
        assert "X-Agent-Voice-Owned=true" in contents
        assert "-m agent_voice control-url %u" in contents
        default = subprocess.run(
            ["xdg-mime", "query", "default", "x-scheme-handler/agent-voice"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert default.stdout.strip() == desktop.name
    else:
        import winreg

        base = r"Software\Classes\agent-voice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
            assert winreg.QueryValueEx(key, "URL Protocol")[0] == ""
            assert winreg.QueryValueEx(key, "AgentVoiceOwned")[0] == "1"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, rf"{base}\shell\open\command"
        ) as key:
            command = winreg.QueryValueEx(key, None)[0]
        assert "-m agent_voice control-url" in command
        assert '"%1"' in command

    removed = run_cli(cli, "controls", "uninstall", "--json")
    assert removed["removed"] is True
    if system == "Linux":
        assert not Path(str(installed["path"])).exists()
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base):
                pass
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("Windows control handler was not removed")


def main() -> None:
    cli = Path(sys.argv[1]).resolve()
    system = platform.system()
    output_dir = Path(os.environ["RUNNER_TEMP"]) / "agent-voice-package-e2e"
    output_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run([str(cli), "setup", "--model", "int8"], check=True)
    offline_doctor = run_cli(cli, "doctor", "--service-url", SERVICE_URL, "--json")
    check_doctor(offline_doctor, "warn")

    local_wav = output_dir / "local.wav"
    local = run_cli(
        cli,
        "speak",
        f"{system} generation verification.",
        "--no-service",
        "--output",
        str(local_wav),
    )
    assert local["backend"] == "local"
    assert "playback" not in local
    validate_wav(local_wav)

    labeled = run_cli(
        cli,
        "speak",
        f"{system} labeled speed verification.",
        "--no-service",
        "--label",
        "Package E2E",
        "--format",
        "mp3",
        "--speed",
        "1.5",
    )
    labeled_path = Path(str(labeled["path"]))
    assert labeled["backend"] == "local"
    assert labeled["speed"] == 1.5
    assert re.fullmatch(
        r"Package-E2E-\d{2}-\d{2}-\d{2}-at-\d{2}-\d{2}\.mp3",
        labeled_path.name,
    )
    assert (
        labeled_path.parent
        == (Path(os.environ["AGENT_VOICE_HOME"]) / "recordings").resolve()
    )
    validate_mp3(labeled_path)
    verify_controls(cli, system, output_dir)

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
                f"{system} localhost service verification.",
                "--service-url",
                SERVICE_URL,
                "--output",
                str(service_wav),
            )
            assert remote["backend"] == "service"
            assert "playback" not in remote
            validate_wav(service_wav)
        finally:
            service.terminate()
            try:
                service.wait(timeout=10)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait(timeout=10)
    print(log_path.read_text(encoding="utf-8", errors="replace"))
    print(f"Verified installed package on {system}")


if __name__ == "__main__":
    main()
