from __future__ import annotations

from agent_voice import doctor
from agent_voice.audio import AudioRuntime
from agent_voice.model import ModelCheck, ModelStatus


class ReadyModel:
    def status(self):
        return ModelStatus(
            ready=True,
            checks=(
                ModelCheck("runtime", "pass", "runtime available"),
                ModelCheck("model", "pass", "model available"),
            ),
        )


def _prepare_doctor(tmp_path, monkeypatch, runtime: AudioRuntime) -> None:
    monkeypatch.setattr(doctor, "recording_dir", lambda: tmp_path / "recordings")
    monkeypatch.setattr(doctor, "inspect_audio_runtime", lambda: runtime)
    monkeypatch.setattr(
        doctor,
        "health_check",
        lambda url: (_ for _ in ()).throw(doctor.ServiceUnavailable("not running")),
    )


def test_bundled_audio_runtime_is_ready(tmp_path, monkeypatch):
    _prepare_doctor(
        tmp_path,
        monkeypatch,
        AudioRuntime(
            ffmpeg_path="/package/imageio_ffmpeg/ffmpeg",
            ffmpeg_version="7.1",
            ffmpeg_error=None,
            miniaudio_version="1.71",
            playback_backend="coreaudio",
            playback_error=None,
        ),
    )

    report = doctor.diagnose(ReadyModel(), "http://127.0.0.1:8765")
    checks = {check["name"]: check for check in report["checks"]}

    assert report["ok"] is True
    assert checks["compressed audio"]["status"] == "pass"
    assert "bundled by imageio-ffmpeg" in checks["compressed audio"]["detail"]
    assert checks["playback"] == {
        "name": "playback",
        "status": "pass",
        "detail": "miniaudio 1.71 · coreaudio",
    }


def test_missing_output_device_is_a_playback_warning(tmp_path, monkeypatch):
    _prepare_doctor(
        tmp_path,
        monkeypatch,
        AudioRuntime(
            ffmpeg_path="/package/imageio_ffmpeg/ffmpeg",
            ffmpeg_version="7.1",
            ffmpeg_error=None,
            miniaudio_version="1.71",
            playback_backend=None,
            playback_error="no suitable audio backend found",
        ),
    )

    report = doctor.diagnose(ReadyModel(), "http://127.0.0.1:8765")
    playback = next(check for check in report["checks"] if check["name"] == "playback")

    assert report["ok"] is True
    assert playback["status"] == "warn"
    assert "output device unavailable" in playback["detail"]
