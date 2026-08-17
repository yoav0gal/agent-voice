from __future__ import annotations

import hashlib
import math
import os
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np
from filelock import FileLock
from numpy.typing import NDArray

from .audio import change_tempo
from .config import DEFAULT_VOICE, MAX_SPEED, MIN_SPEED
from .model import (
    LanguageCatalog,
    ModelCapability,
    ModelCheck,
    ModelDescriptor,
    ModelSelection,
    ModelStatus,
    NamedVoice,
    PreparedArtifact,
    SetupReceipt,
    Speech,
    SynthesisRequest,
    UnsupportedCapability,
    VoiceCatalog,
)
from .paths import model_dir

KOKORO_MODEL_ID = "kokoro"
KOKORO_DISPLAY_NAME = "Kokoro-82M"
KOKORO_RUNTIME_NAME = "kokoro-onnx"
KOKORO_NATURAL_SPEED = 1.0
KOKORO_MAX_TEXT_CHARACTERS = 50_000
# Voice styles are indexed by token count, so the 510-row table ends at 509.
KOKORO_MAX_PHONEMES = 509
DEFAULT_KOKORO_VARIANT = "int8"
RELEASE_BASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)

_MODEL_ASSETS = {
    "int8": (
        "kokoro-v1.0.int8.onnx",
        92_361_271,
        "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    ),
    "fp16": (
        "kokoro-v1.0.fp16.onnx",
        177_464_787,
        "c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204",
    ),
    "full": (
        "kokoro-v1.0.onnx",
        325_532_387,
        "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    ),
}
_VOICES_ASSET = (
    "voices-v1.0.bin",
    28_214_398,
    "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
)
KOKORO_VARIANTS = tuple(_MODEL_ASSETS)
KOKORO_LANGUAGES = (
    ("American English", "en-us", "a"),
    ("British English", "en-gb", "b"),
    ("Japanese", "ja", "j"),
    ("Mandarin Chinese", "cmn", "z"),
    ("Spanish", "es", "e"),
    ("French", "fr-fr", "f"),
    ("Hindi", "hi", "h"),
    ("Italian", "it", "i"),
    ("Brazilian Portuguese", "pt-br", "p"),
)

Asset = tuple[str, int, str]


class _KokoroRuntime(Protocol):
    def get_voices(self) -> list[str]: ...

    def create(
        self, text: str, *, voice: str, speed: float, lang: str
    ) -> tuple[NDArray[np.floating], int]: ...


RuntimeFactory = Callable[[Path, Path], _KokoroRuntime]


class KokoroAdapter:
    """Kokoro model lifecycle and inference behind the speech-model seam."""

    def __init__(
        self,
        selection: ModelSelection | None = None,
        *,
        runtime_factory: RuntimeFactory | None = None,
    ) -> None:
        requested = selection or ModelSelection(KOKORO_MODEL_ID, DEFAULT_KOKORO_VARIANT)
        if requested.model_id != KOKORO_MODEL_ID:
            raise ValueError(
                f"Kokoro adapter cannot load model identity '{requested.model_id}'"
            )
        variant = requested.variant or DEFAULT_KOKORO_VARIANT
        if variant not in _MODEL_ASSETS:
            choices = ", ".join(KOKORO_VARIANTS)
            raise ValueError(
                f"Unknown Kokoro variant '{variant}'. Choose one of: {choices}"
            )
        self._selection = ModelSelection(KOKORO_MODEL_ID, variant)
        self._runtime_factory = runtime_factory or _load_runtime
        self._uses_default_runtime = runtime_factory is None
        self._runtime: _KokoroRuntime | None = None
        self._prepared = False
        self._setup_lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def descriptor(self) -> ModelDescriptor:
        return ModelDescriptor(
            selection=self._selection,
            display_name=KOKORO_DISPLAY_NAME,
            runtime=KOKORO_RUNTIME_NAME,
            capabilities=frozenset(
                {ModelCapability.NAMED_VOICES, ModelCapability.LANGUAGE_TAGS}
            ),
        )

    def setup(self, *, force: bool = False) -> SetupReceipt:
        model, voices = self._asset_paths()
        with self._setup_lock:
            if not self._prepared or force:
                model.parent.mkdir(parents=True, exist_ok=True)
                _download_asset(_MODEL_ASSETS[self.variant], model, force)
                _download_asset(_VOICES_ASSET, voices, force)
                self._prepared = True
                if force:
                    with self._load_lock:
                        self._runtime = None
            return SetupReceipt(
                (
                    PreparedArtifact("Ready", model),
                    PreparedArtifact("Voices", voices),
                )
            )

    def status(self) -> ModelStatus:
        runtime_check = self._runtime_check()
        assets_ready = self._assets_ready()
        model_path, _ = self._asset_paths()
        model_check = ModelCheck(
            "model",
            "pass" if assets_ready else "warn",
            (
                f"{self.variant} verified in {model_path.parent}"
                if assets_ready
                else (
                    f"{self.variant} not ready; run "
                    "agent-voice setup --model-id kokoro "
                    f"--variant {self.variant}"
                )
            ),
        )
        return ModelStatus(
            ready=runtime_check.status == "pass" and assets_ready,
            checks=(runtime_check, model_check),
            setup_hint=(
                None
                if assets_ready
                else (f"agent-voice setup --model-id kokoro --variant {self.variant}")
            ),
        )

    def voice_catalog(self) -> VoiceCatalog:
        self.setup()
        voices = tuple(NamedVoice(name) for name in self._get_runtime().get_voices())
        return VoiceCatalog(
            named=voices,
            default=NamedVoice(DEFAULT_VOICE),
            accepts_reference_audio=False,
            languages=tuple(
                LanguageCatalog(
                    name,
                    tag,
                    tuple(voice for voice in voices if voice.name.startswith(prefix)),
                )
                for name, tag, prefix in KOKORO_LANGUAGES
            ),
        )

    def synthesize(self, request: SynthesisRequest) -> Speech:
        text = request.text.strip()
        if not text:
            raise ValueError("Text cannot be empty")
        if len(text) > KOKORO_MAX_TEXT_CHARACTERS:
            raise ValueError(
                "Text is too long "
                f"(maximum {KOKORO_MAX_TEXT_CHARACTERS:,} characters per request)"
            )
        if (
            isinstance(request.speed, bool)
            or not isinstance(request.speed, (int, float))
            or not math.isfinite(request.speed)
            or not MIN_SPEED <= request.speed <= MAX_SPEED
        ):
            raise ValueError(f"Speed must be between {MIN_SPEED} and {MAX_SPEED}")

        if request.voice is None:
            voice = DEFAULT_VOICE
        elif isinstance(request.voice, NamedVoice):
            voice = request.voice.name
        else:
            raise UnsupportedCapability(
                "Kokoro supports named voices, not reference audio"
            )
        language = "en-us" if request.language is None else request.language.strip()
        if not language:
            raise ValueError("Language tag must not be empty")

        self.setup()
        runtime = self._get_runtime()
        if voice not in runtime.get_voices():
            raise ValueError(f"Unknown voice '{voice}'")

        started = time.perf_counter()
        with self._inference_lock:
            samples, sample_rate = runtime.create(
                text,
                voice=voice,
                speed=KOKORO_NATURAL_SPEED,
                lang=language,
            )
        samples = change_tempo(samples, sample_rate, float(request.speed))
        return Speech(samples, sample_rate, time.perf_counter() - started)

    @property
    def variant(self) -> str:
        variant = self._selection.variant
        assert variant is not None
        return variant

    def _runtime_check(self) -> ModelCheck:
        if not self._uses_default_runtime:
            return ModelCheck("runtime", "pass", "injected runtime available")
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError as error:
            return ModelCheck("runtime", "fail", str(error))
        return ModelCheck("runtime", "pass", "kokoro-onnx importable")

    def _get_runtime(self) -> _KokoroRuntime:
        if self._runtime is None:
            with self._load_lock:
                if self._runtime is None:
                    model, voices = self._asset_paths()
                    self._runtime = self._runtime_factory(model, voices)
        return self._runtime

    def _asset_paths(self) -> tuple[Path, Path]:
        directory = model_dir()
        return (
            directory / _MODEL_ASSETS[self.variant][0],
            directory / _VOICES_ASSET[0],
        )

    def _assets_ready(self) -> bool:
        model, voices = self._asset_paths()
        return _valid_asset(model, _MODEL_ASSETS[self.variant]) and _valid_asset(
            voices, _VOICES_ASSET
        )


def _load_runtime(model: Path, voices: Path) -> _KokoroRuntime:
    from kokoro_onnx import Kokoro

    class AgentVoiceKokoro(Kokoro):
        @staticmethod
        def _split_phonemes(phonemes: str) -> list[str]:
            return _split_phonemes(phonemes)

    return AgentVoiceKokoro(str(model), str(voices))


def _split_phonemes(phonemes: str) -> list[str]:
    """Keep every phoneme while preferring natural batch boundaries."""
    chunks: list[str] = []
    remaining = phonemes.strip()
    while len(remaining) > KOKORO_MAX_PHONEMES:
        window = remaining[:KOKORO_MAX_PHONEMES]
        split_at = max(window.rfind(mark) for mark in ".,!?;:") + 1
        if split_at <= 1:
            split_at = window.rfind(" ")
        if split_at <= 0:
            split_at = KOKORO_MAX_PHONEMES
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _valid_asset(path: Path, asset: Asset) -> bool:
    _, expected_size, expected_sha256 = asset
    return (
        path.is_file()
        and path.stat().st_size == expected_size
        and _sha256(path) == expected_sha256
    )


def _download_asset(asset: Asset, destination: Path, force: bool) -> None:
    name, expected_size, expected_sha256 = asset
    lock_path = destination.with_suffix(destination.suffix + ".lock")
    with FileLock(lock_path):
        if not force and _valid_asset(destination, asset):
            print(f"✓ {name} already downloaded and verified", file=sys.stderr)
            return

        handle, partial_name = tempfile.mkstemp(
            prefix=f".{name}.", suffix=".part", dir=destination.parent
        )
        os.close(handle)
        partial = Path(partial_name)
        url = f"{RELEASE_BASE}/{name}"
        print(
            f"↓ Downloading {name} ({expected_size / 1_000_000:.1f} MB)",
            file=sys.stderr,
        )

        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "agent-voice/0.5"}
            )
            with (
                urllib.request.urlopen(request, timeout=30) as response,
                partial.open("wb") as output,
            ):
                downloaded = 0
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    downloaded += len(chunk)
                    print(
                        f"\r  {downloaded / expected_size:6.1%}",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
            print(file=sys.stderr)
            actual_size = partial.stat().st_size
            if actual_size != expected_size:
                raise RuntimeError(
                    f"Download size mismatch for {name}: "
                    f"got {actual_size}, expected {expected_size}"
                )
            actual_sha256 = _sha256(partial)
            if actual_sha256 != expected_sha256:
                raise RuntimeError(
                    f"Checksum mismatch for {name}: "
                    f"got {actual_sha256}, expected {expected_sha256}"
                )
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
