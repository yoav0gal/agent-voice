from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .audio import play_audio, write_audio
from .client import (
    DEFAULT_SERVICE_URL,
    ServiceUnavailable,
    ensure_service,
    request_speech,
)
from .config import (
    DEFAULT_SERVICE_TIMEOUT_MINUTES,
    FORMATS,
    SERVICE_MODES,
    SpeechDefaults,
    load_defaults,
)
from .delivery import Delivery, prepare_delivery
from .model import (
    ModelSelection,
    NamedVoice,
    Recording,
    SpeechModel,
    SynthesisRequest,
)
from .paths import resolved_recording_dir
from .registry import MODEL_REGISTRY


@dataclass(frozen=True)
class SpeakRequest:
    text: str
    selection: ModelSelection
    output: Path | None = None
    label: str | None = None
    output_dir: Path | None = None
    format: str | None = None
    voice: str | None = None
    speed: float | None = None
    language: str = "en-us"
    play: bool = False
    service: str | None = None
    service_timeout_minutes: float | None = None
    service_url: str = DEFAULT_SERVICE_URL


@dataclass(frozen=True)
class SpeakReceipt:
    recording: Recording
    selection: ModelSelection
    played: bool
    delivery: Delivery
    service_fallback: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = self.recording.to_dict()
        payload["model_id"] = self.selection.model_id
        payload["variant"] = self.selection.variant
        payload["played"] = self.played
        if self.service_fallback:
            payload["service_fallback"] = True
        payload["file_uri"] = self.recording.path.resolve().as_uri()
        delivery: dict[str, object] = {
            "fallback_markdown": self.delivery.fallback_markdown
        }
        if self.delivery.browser_url is not None:
            delivery.update(
                {
                    "browser_url": self.delivery.browser_url,
                    "audio_url": self.delivery.audio_url,
                    "recording_path": str(self.delivery.recording_path),
                }
            )
        payload["delivery"] = delivery
        return payload


@dataclass(frozen=True)
class _OutputPlan:
    destination: Path
    audio_format: str
    recording_root: Path
    reserved: bool


@dataclass(frozen=True)
class _ResolvedSpeakRequest:
    text: str
    selection: ModelSelection
    output: _OutputPlan
    voice: str
    speed: float
    language: str
    play: bool
    service: str
    service_timeout_minutes: float | None
    service_url: str


class _RecordingGenerator(Protocol):
    def generate(self, request: _ResolvedSpeakRequest) -> Recording: ...


class _DeliveryPreparer(Protocol):
    def __call__(
        self,
        recording: Path,
        text: str,
        *,
        audio_format: str,
        recordings_dir: Path,
    ) -> Delivery: ...


class _EmbeddedGenerator:
    def __init__(
        self,
        model_factory: Callable[[ModelSelection], SpeechModel],
    ) -> None:
        self._model_factory = model_factory

    def generate(self, request: _ResolvedSpeakRequest) -> Recording:
        speech = self._model_factory(request.selection).synthesize(
            SynthesisRequest(
                text=request.text,
                voice=NamedVoice(request.voice),
                speed=request.speed,
                language=request.language,
            )
        )
        path = write_audio(
            speech.samples,
            speech.sample_rate,
            request.output.destination,
            request.output.audio_format,
        )
        return Recording(
            path=path,
            format=request.output.audio_format,
            voice=request.voice,
            speed=request.speed,
            sample_rate=speech.sample_rate,
            duration_seconds=round(speech.duration_seconds, 3),
            generation_seconds=round(speech.elapsed_seconds, 3),
            backend="local",
        )


class _ServiceGenerator:
    def generate(self, request: _ResolvedSpeakRequest) -> Recording:
        ensure_service(
            request.service_url,
            request.selection,
            request.service_timeout_minutes,
        )
        return request_speech(
            request.service_url,
            request.text,
            request.output.destination,
            request.output.audio_format,
            request.voice,
            request.speed,
            request.language,
            selection=request.selection,
        )


class Speaker:
    """Resolve and execute one complete speaking request."""

    def __init__(
        self,
        *,
        defaults_loader: Callable[[], SpeechDefaults] = load_defaults,
        embedded: _RecordingGenerator | None = None,
        service: _RecordingGenerator | None = None,
        playback: Callable[[Path], None] = play_audio,
        delivery: _DeliveryPreparer = prepare_delivery,
        now: Callable[[], datetime] = datetime.now,
        notice: Callable[[str], None] | None = None,
    ) -> None:
        self._defaults_loader = defaults_loader
        self._embedded = (
            embedded
            if embedded is not None
            else _EmbeddedGenerator(MODEL_REGISTRY.create)
        )
        self._service = service if service is not None else _ServiceGenerator()
        self._playback = playback
        self._delivery = delivery
        self._now = now
        self._notice = notice or (lambda message: print(message, file=sys.stderr))

    def speak(self, request: SpeakRequest) -> SpeakReceipt:
        defaults = self._defaults_loader()
        resolved = self._resolve(request, defaults)
        fallback = False
        try:
            if resolved.service == "off":
                recording = self._embedded.generate(resolved)
            else:
                try:
                    recording = self._service.generate(resolved)
                except ServiceUnavailable as error:
                    fallback = True
                    self._notice(
                        "Agent Voice service unavailable; using embedded inference "
                        f"({error})"
                    )
                    recording = self._embedded.generate(resolved)
            _require_planned_recording(recording, resolved.output)
        except BaseException:
            if resolved.output.reserved:
                resolved.output.destination.unlink(missing_ok=True)
            raise

        if resolved.play:
            self._playback(recording.path)
        delivery = self._delivery(
            recording.path,
            resolved.text,
            audio_format=recording.format,
            recordings_dir=resolved.output.recording_root,
        )
        if delivery.warning is not None:
            self._notice(f"Warning: {delivery.warning}")
        return SpeakReceipt(
            recording=recording,
            selection=resolved.selection,
            played=resolved.play,
            delivery=delivery,
            service_fallback=fallback,
        )

    def _resolve(
        self,
        request: SpeakRequest,
        defaults: SpeechDefaults,
    ) -> _ResolvedSpeakRequest:
        service, timeout = _resolve_service_policy(request, defaults)
        return _ResolvedSpeakRequest(
            text=request.text,
            selection=request.selection,
            output=self._plan_output(request, defaults),
            voice=request.voice if request.voice is not None else defaults.voice,
            speed=request.speed if request.speed is not None else defaults.speed,
            language=request.language,
            play=request.play,
            service=service,
            service_timeout_minutes=timeout,
            service_url=request.service_url,
        )

    def _plan_output(
        self,
        request: SpeakRequest,
        defaults: SpeechDefaults,
    ) -> _OutputPlan:
        audio_format = request.format if request.format is not None else defaults.format
        if audio_format not in FORMATS:
            raise ValueError(f"Output format must be one of: {', '.join(FORMATS)}")
        recording_root = resolved_recording_dir(defaults.output_dir)
        if request.output is not None:
            ignored = [
                option
                for option, supplied in (
                    ("--label", bool(request.label)),
                    ("--output-dir", request.output_dir is not None),
                )
                if supplied
            ]
            if ignored:
                self._notice(
                    "Warning: --output specifies the exact destination; ignoring "
                    f"{' and '.join(ignored)}"
                )
            suffix = request.output.suffix.lower().lstrip(".")
            if suffix:
                if suffix not in FORMATS:
                    raise ValueError(
                        f"Output extension must be one of: {', '.join(FORMATS)}"
                    )
                audio_format = suffix
            return _OutputPlan(
                request.output,
                audio_format,
                recording_root,
                False,
            )

        directory = (
            request.output_dir.expanduser().resolve()
            if request.output_dir is not None
            else recording_root
        )
        timestamp = self._now().strftime("%m-%d-%y-at-%H-%M")
        label = _filename_label(request.label) if request.label else "agent-voice"
        return _OutputPlan(
            _reserve_recording_path(label, timestamp, audio_format, directory),
            audio_format,
            recording_root,
            True,
        )


def _resolve_service_policy(
    request: SpeakRequest,
    defaults: SpeechDefaults,
) -> tuple[str, float | None]:
    configured = defaults.service
    service = request.service if request.service is not None else configured.mode
    if service not in SERVICE_MODES:
        raise ValueError(f"Service mode must be one of: {', '.join(SERVICE_MODES)}")
    requested_timeout = request.service_timeout_minutes
    if requested_timeout is not None and service != "timed":
        raise ValueError("--service-timeout can only be used with --service timed")
    if service != "timed":
        return service, None
    if requested_timeout is not None:
        return service, requested_timeout
    if configured.mode == "timed":
        return service, configured.timeout_minutes
    return service, DEFAULT_SERVICE_TIMEOUT_MINUTES


def _require_planned_recording(
    recording: Recording,
    output: _OutputPlan,
) -> None:
    if recording.path.resolve() != output.destination.expanduser().resolve():
        raise RuntimeError("Speech backend returned an unexpected recording path")
    if recording.format != output.audio_format:
        raise RuntimeError("Speech backend returned an unexpected recording format")


def _filename_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    label = label[:48].rstrip("-")
    if not label:
        raise ValueError("Label must contain at least one ASCII letter or number")
    return label


def _reserve_recording_path(
    label: str,
    timestamp: str,
    audio_format: str,
    directory: Path,
) -> Path:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RuntimeError(
            f"Could not create output directory {directory}: {error}"
        ) from error
    if not directory.is_dir():
        raise ValueError(f"Output directory is not a directory: {directory}")
    stem = f"{label}-{timestamp}"
    collision = 2
    output = directory / f"{stem}.{audio_format}"
    while True:
        try:
            descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            output = directory / f"{stem}-{collision}.{audio_format}"
            collision += 1
        else:
            os.close(descriptor)
            return output
