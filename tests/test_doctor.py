from __future__ import annotations

from kokoro_cli import doctor


def test_windows_playback_is_reported_as_experimental(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setattr(doctor, "models_ready", lambda variant: True)
    monkeypatch.setattr(doctor, "model_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(doctor, "recording_dir", lambda: tmp_path / "recordings")
    monkeypatch.setattr(
        doctor.shutil,
        "which",
        lambda name: r"C:\ffmpeg\bin\ffplay.exe" if name == "ffplay" else None,
    )
    monkeypatch.setattr(
        doctor,
        "health_check",
        lambda url: (_ for _ in ()).throw(doctor.ServiceUnavailable("not running")),
    )

    report = doctor.diagnose("int8", "http://127.0.0.1:8765")
    playback = next(check for check in report["checks"] if check["name"] == "playback")

    assert playback["status"] == "warn"
    assert "experimental" in playback["detail"]
    assert "not exercised by CI" in playback["detail"]
