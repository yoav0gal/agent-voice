from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from agent_voice.client import ServiceUnavailable
from agent_voice.config import SpeechDefaults, update_defaults
from agent_voice.delivery import Delivery
from agent_voice.model import ModelSelection, Recording
from agent_voice.speaking import SpeakReceipt, SpeakRequest, Speaker


SELECTION = ModelSelection("kokoro", "int8")


class FakeGenerator:
    def __init__(
        self,
        *,
        backend: str,
        audio: bytes = b"recording",
        error: Exception | None = None,
    ) -> None:
        self.backend = backend
        self.audio = audio
        self.error = error
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        destination = request.output.destination.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.audio)
        return Recording(
            path=destination,
            format=request.output.audio_format,
            voice=request.voice,
            speed=request.speed,
            sample_rate=24_000,
            duration_seconds=1.0,
            generation_seconds=0.1,
            backend=self.backend,
        )


def delivery_success(calls: list | None = None):
    def prepare(
        recording,
        text,
        *,
        source_text,
        language,
        audio_format,
        recordings_dir,
        controls,
    ):
        if calls is not None:
            calls.append(
                (
                    recording,
                    text,
                    source_text,
                    language,
                    audio_format,
                    recordings_dir,
                    controls,
                )
            )
        resolved = recording.resolve()
        return Delivery(
            browser_url="http://127.0.0.1:49123/player/recording.html",
            audio_url="http://127.0.0.1:49123/recordings/recording.mp3",
            recording_path=resolved,
        )

    return prepare


def make_speaker(
    tmp_path,
    *,
    defaults: SpeechDefaults | None = None,
    embedded: FakeGenerator | None = None,
    service: FakeGenerator | None = None,
    playback=None,
    delivery=None,
    notices: list[str] | None = None,
    now=None,
):
    selected_defaults = defaults or SpeechDefaults(output_dir=str(tmp_path))
    return Speaker(
        defaults_loader=lambda: selected_defaults,
        embedded=embedded or FakeGenerator(backend="local"),
        service=service or FakeGenerator(backend="service"),
        playback=playback or (lambda _path: None),
        delivery=delivery or delivery_success(),
        notice=(notices.append if notices is not None else lambda _message: None),
        now=now or (lambda: datetime(2026, 7, 26, 10, 13)),
    )


def test_no_service_uses_embedded_generation(tmp_path):
    embedded = FakeGenerator(backend="local")
    service = FakeGenerator(backend="service")
    receipt = make_speaker(
        tmp_path,
        embedded=embedded,
        service=service,
    ).speak(SpeakRequest("Visible text.", SELECTION, no_service=True))

    assert receipt.recording.backend == "local"
    assert receipt.recording.path.read_bytes() == b"recording"
    assert len(embedded.requests) == 1
    assert service.requests == []
    assert receipt.service_fallback is False


def test_service_generation_uses_configured_timeout(tmp_path):
    service = FakeGenerator(backend="service", audio=b"service")
    defaults = SpeechDefaults(
        service_timeout_minutes=2.5,
        output_dir=str(tmp_path),
    )

    receipt = make_speaker(
        tmp_path,
        defaults=defaults,
        service=service,
    ).speak(SpeakRequest("Visible text.", SELECTION))

    assert receipt.recording.backend == "service"
    assert receipt.recording.path.read_bytes() == b"service"
    assert service.requests[0].no_service is False
    assert service.requests[0].service_timeout_minutes == 2.5


def test_unavailable_service_falls_back_to_embedded(tmp_path):
    service = FakeGenerator(
        backend="service",
        error=ServiceUnavailable("not running"),
    )
    embedded = FakeGenerator(backend="local", audio=b"local")
    notices = []

    receipt = make_speaker(
        tmp_path,
        embedded=embedded,
        service=service,
        notices=notices,
    ).speak(SpeakRequest("Visible text.", SELECTION))

    assert receipt.recording.backend == "local"
    assert receipt.service_fallback is True
    assert receipt.recording.path.read_bytes() == b"local"
    assert notices == [
        "Agent Voice service unavailable; using embedded inference (not running)"
    ]


def test_non_availability_service_errors_do_not_fallback(tmp_path):
    service = FakeGenerator(backend="service", error=ValueError("bad request"))
    embedded = FakeGenerator(backend="local")

    with pytest.raises(ValueError, match="bad request"):
        make_speaker(
            tmp_path,
            embedded=embedded,
            service=service,
        ).speak(SpeakRequest("Visible text.", SELECTION))

    assert embedded.requests == []


def test_saved_defaults_and_request_values_resolve_once(tmp_path):
    embedded = FakeGenerator(backend="local")
    defaults = SpeechDefaults(
        voice="bf_emma",
        speed=1.15,
        format="opus",
        output_dir=str(tmp_path),
    )

    receipt = make_speaker(
        tmp_path,
        defaults=defaults,
        embedded=embedded,
    ).speak(SpeakRequest("Visible text.", SELECTION, no_service=True))

    resolved = embedded.requests[0]
    assert (resolved.voice, resolved.speed) == ("bf_emma", 1.15)
    assert receipt.recording.format == "opus"
    assert receipt.recording.path.suffix == ".opus"


def test_request_values_override_saved_defaults(tmp_path):
    embedded = FakeGenerator(backend="local")
    defaults = SpeechDefaults(
        voice="af_heart",
        speed=1.0,
        format="mp3",
        output_dir=str(tmp_path / "configured"),
    )
    command_line = tmp_path / "command-line"

    receipt = make_speaker(
        tmp_path,
        defaults=defaults,
        embedded=embedded,
    ).speak(
        SpeakRequest(
            "Visible text.",
            SELECTION,
            output_dir=command_line,
            format="wav",
            voice="bf_emma",
            speed=1.25,
            no_service=True,
        )
    )

    resolved = embedded.requests[0]
    assert (resolved.voice, resolved.speed, resolved.no_service) == (
        "bf_emma",
        1.25,
        True,
    )
    assert receipt.recording.path.parent == command_line
    assert receipt.recording.path.suffix == ".wav"


def test_environment_recording_root_overrides_config(tmp_path, monkeypatch):
    environment = tmp_path / "environment"
    configured = tmp_path / "configured"
    monkeypatch.setenv("AGENT_VOICE_RECORDING_DIR", str(environment))
    calls = []
    defaults = SpeechDefaults(
        output_dir=str(configured),
    )

    receipt = make_speaker(
        tmp_path,
        defaults=defaults,
        delivery=delivery_success(calls),
    ).speak(SpeakRequest("Visible text.", SELECTION, no_service=True))

    assert receipt.recording.path.parent == environment
    assert calls[0][5] == environment
    assert not configured.exists()


def test_live_config_cli_and_environment_precedence(tmp_path, monkeypatch):
    home = tmp_path / "home"
    configured = tmp_path / "configured"
    environment = tmp_path / "environment"
    command_line = tmp_path / "command-line"
    monkeypatch.setenv("AGENT_VOICE_HOME", str(home))
    update_defaults(
        voice="bf_emma",
        speed=1.15,
        format="opus",
        output_dir=configured,
    )
    monkeypatch.setenv("AGENT_VOICE_RECORDING_DIR", str(environment))
    calls = []

    receipt = Speaker(
        embedded=FakeGenerator(backend="local"),
        service=FakeGenerator(backend="service"),
        delivery=delivery_success(calls),
        notice=lambda _message: None,
        now=lambda: datetime(2026, 7, 26, 10, 13),
    ).speak(
        SpeakRequest(
            "Visible text.",
            SELECTION,
            output_dir=command_line,
            format="wav",
            voice="af_nova",
            no_service=True,
        )
    )

    assert receipt.recording.path.parent == command_line
    assert receipt.recording.format == "wav"
    assert receipt.recording.voice == "af_nova"
    assert receipt.recording.speed == 1.15
    assert calls[0][5] == environment


def test_exact_output_takes_precedence_and_extension_selects_format(tmp_path):
    output = tmp_path / "exact.wav"
    ignored = tmp_path / "ignored"
    notices = []

    receipt = make_speaker(tmp_path, notices=notices).speak(
        SpeakRequest(
            "Visible text.",
            SELECTION,
            output=output,
            label="ignored",
            output_dir=ignored,
            format="mp3",
            no_service=True,
        )
    )

    assert receipt.recording.path == output
    assert receipt.recording.format == "wav"
    assert not ignored.exists()
    assert notices == [
        "Warning: --output specifies the exact destination; "
        "ignoring --label and --output-dir"
    ]


def test_extensionless_exact_output_uses_selected_format(tmp_path):
    output = tmp_path / "exact"

    receipt = make_speaker(tmp_path).speak(
        SpeakRequest(
            "Visible text.",
            SELECTION,
            output=output,
            format="m4a",
            no_service=True,
        )
    )

    assert receipt.recording.path == output
    assert receipt.recording.format == "m4a"


@pytest.mark.parametrize("audio_format", ("wav", "mp3", "opus", "m4a"))
def test_managed_output_supports_each_public_format(tmp_path, audio_format):
    receipt = make_speaker(tmp_path).speak(
        SpeakRequest(
            "Visible text.",
            SELECTION,
            format=audio_format,
            no_service=True,
        )
    )

    assert receipt.recording.format == audio_format
    assert receipt.recording.path.suffix == f".{audio_format}"


def test_managed_output_uses_portable_label_and_collision_suffix(tmp_path):
    existing = tmp_path / "Daily-update-07-26-26-at-10-13.mp3"
    existing.write_bytes(b"existing")

    receipt = make_speaker(tmp_path).speak(
        SpeakRequest(
            "Visible text.",
            SELECTION,
            label="Daily update!",
            no_service=True,
        )
    )

    assert receipt.recording.path.name == "Daily-update-07-26-26-at-10-13-2.mp3"
    assert existing.read_bytes() == b"existing"


def test_managed_reservations_are_unique_across_speakers(tmp_path):
    def speak(_index):
        return (
            make_speaker(tmp_path)
            .speak(
                SpeakRequest("Visible text.", SELECTION, label="SR", no_service=True)
            )
            .recording.path
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(executor.map(speak, range(8)))

    assert len(set(paths)) == 8
    assert all(path.is_file() for path in paths)


def test_failed_managed_generation_removes_reservation(tmp_path):
    embedded = FakeGenerator(backend="local", error=RuntimeError("failed"))

    with pytest.raises(RuntimeError, match="failed"):
        make_speaker(tmp_path, embedded=embedded).speak(
            SpeakRequest("Visible text.", SELECTION, label="SR", no_service=True)
        )

    assert list(tmp_path.iterdir()) == []


def test_failed_exact_generation_preserves_existing_destination(tmp_path):
    output = tmp_path / "existing.mp3"
    output.write_bytes(b"existing")
    embedded = FakeGenerator(backend="local", error=RuntimeError("failed"))

    with pytest.raises(RuntimeError, match="failed"):
        make_speaker(tmp_path, embedded=embedded).speak(
            SpeakRequest(
                "Visible text.",
                SELECTION,
                output=output,
                no_service=True,
            )
        )

    assert output.read_bytes() == b"existing"


@pytest.mark.parametrize(
    ("path_change", "format_change", "message"),
    [
        (True, False, "unexpected recording path"),
        (False, True, "unexpected recording format"),
    ],
)
def test_backend_must_honor_the_single_output_plan(
    tmp_path,
    path_change,
    format_change,
    message,
):
    class DriftingGenerator(FakeGenerator):
        def generate(self, request):
            recording = super().generate(request)
            return Recording(
                path=(
                    recording.path.with_name("other.mp3")
                    if path_change
                    else recording.path
                ),
                format="wav" if format_change else recording.format,
                voice=recording.voice,
                speed=recording.speed,
                sample_rate=recording.sample_rate,
                duration_seconds=recording.duration_seconds,
                generation_seconds=recording.generation_seconds,
                backend=recording.backend,
            )

    with pytest.raises(RuntimeError, match=message):
        make_speaker(
            tmp_path,
            embedded=DriftingGenerator(backend="local"),
        ).speak(SpeakRequest("Visible text.", SELECTION, no_service=True))

    assert list(tmp_path.iterdir()) == []


def test_played_becomes_true_only_after_playback_returns(tmp_path):
    events = []

    def playback(path):
        events.append(path)

    receipt = make_speaker(tmp_path, playback=playback).speak(
        SpeakRequest("Visible text.", SELECTION, play=True, no_service=True)
    )

    assert events == [receipt.recording.path]
    assert receipt.played is True


def test_playback_failure_does_not_produce_a_truthful_receipt(tmp_path):
    def fail(_path):
        raise RuntimeError("no audio device")

    with pytest.raises(RuntimeError, match="no audio device"):
        make_speaker(tmp_path, playback=fail).speak(
            SpeakRequest("Visible text.", SELECTION, play=True, no_service=True)
        )


def test_delivery_receives_the_planned_recording_root(tmp_path):
    calls = []
    recording_root = tmp_path / "managed"
    output = tmp_path / "external" / "response.mp3"
    defaults = SpeechDefaults(
        output_dir=str(recording_root),
    )

    receipt = make_speaker(
        tmp_path,
        defaults=defaults,
        delivery=delivery_success(calls),
    ).speak(
        SpeakRequest(
            "Visible text.",
            SELECTION,
            output=output,
            no_service=True,
        )
    )

    assert calls == [
        (
            output,
            "Visible text.",
            "Visible text.",
            "en-us",
            "mp3",
            recording_root,
            False,
        )
    ]
    assert receipt.delivery.browser_url is not None


def test_delivery_prefers_the_written_response(tmp_path):
    calls = []

    make_speaker(tmp_path, delivery=delivery_success(calls)).speak(
        SpeakRequest(
            "Spoken narration.",
            SELECTION,
            response_markdown="# Written response",
            language="he-il",
            controls=True,
            no_service=True,
        )
    )

    assert calls[0][1] == "# Written response"
    assert calls[0][2] == "Spoken narration."
    assert calls[0][3] == "he-il"
    assert calls[0][6] is True


def test_delivery_failure_facts_are_typed_serialized_and_reported(tmp_path):
    notices = []

    def fallback(
        recording,
        text,
        *,
        source_text,
        language,
        audio_format,
        recordings_dir,
        controls,
    ):
        return Delivery(warning="viewer unavailable")

    receipt = make_speaker(
        tmp_path,
        delivery=fallback,
        notices=notices,
    ).speak(SpeakRequest("Visible text.", SELECTION, no_service=True))

    assert receipt.to_dict()["delivery"] == {}
    assert notices == ["Warning: viewer unavailable"]


def test_receipt_serialization_preserves_public_json_shape(tmp_path):
    recording = Recording(
        path=tmp_path / "recording.mp3",
        format="mp3",
        voice="af_heart",
        speed=1.0,
        sample_rate=24_000,
        duration_seconds=1.234,
        generation_seconds=0.456,
        backend="service",
    )
    delivery = Delivery(
        browser_url="http://127.0.0.1:49123/player/recording.html",
        audio_url="http://127.0.0.1:49123/recordings/recording.mp3",
        recording_path=recording.path,
        controls={"toggle": "agent-voice://control/token/toggle"},
    )

    receipt = SpeakReceipt(
        recording=recording,
        selection=ModelSelection("kokoro", "fp16"),
        played=False,
        delivery=delivery,
        service_fallback=True,
    )

    assert receipt.to_dict() == {
        "path": str(recording.path),
        "format": "mp3",
        "voice": "af_heart",
        "speed": 1.0,
        "sample_rate": 24_000,
        "duration_seconds": 1.234,
        "generation_seconds": 0.456,
        "backend": "service",
        "model_id": "kokoro",
        "variant": "fp16",
        "played": False,
        "service_fallback": True,
        "file_uri": recording.path.as_uri(),
        "delivery": {
            "browser_url": "http://127.0.0.1:49123/player/recording.html",
            "audio_url": "http://127.0.0.1:49123/recordings/recording.mp3",
            "recording_path": str(recording.path),
            "controls": {"toggle": "agent-voice://control/token/toggle"},
        },
    }


def test_public_interface_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError, match="Output format"):
        make_speaker(tmp_path).speak(
            SpeakRequest(
                "Visible text.",
                SELECTION,
                format="flac",
                no_service=True,
            )
        )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Review CLI status - SR", "Review-CLI-status-SR"),
        ("  spaced / punctuation  ", "spaced-punctuation"),
        ("A" * 60, "A" * 48),
    ],
)
def test_managed_label_is_portable_and_bounded(tmp_path, label, expected):
    receipt = make_speaker(tmp_path).speak(
        SpeakRequest("Visible text.", SELECTION, label=label, no_service=True)
    )

    assert receipt.recording.path.name.startswith(f"{expected}-")


def test_managed_label_rejects_values_without_ascii_letters_or_numbers(tmp_path):
    with pytest.raises(ValueError, match="at least one ASCII"):
        make_speaker(tmp_path).speak(
            SpeakRequest("Visible text.", SELECTION, label="🎙️ ---", no_service=True)
        )
