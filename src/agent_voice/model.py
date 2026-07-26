from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, TypeAlias

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class ModelSelection:
    model_id: str
    variant: str | None = None

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("Model identity must not be empty")
        if self.variant is not None and not self.variant.strip():
            raise ValueError("Model variant must not be empty")


class ModelCapability(StrEnum):
    NAMED_VOICES = "named-voices"
    REFERENCE_AUDIO = "reference-audio"
    LANGUAGE_TAGS = "language-tags"


@dataclass(frozen=True)
class NamedVoice:
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Voice name must not be empty")


@dataclass(frozen=True)
class ReferenceVoice:
    path: Path


VoiceSelection: TypeAlias = NamedVoice | ReferenceVoice | None


@dataclass(frozen=True)
class SynthesisRequest:
    text: str
    voice: VoiceSelection = None
    speed: float = 1.0
    language: str | None = None


@dataclass(frozen=True)
class Speech:
    samples: NDArray[np.floating]
    sample_rate: int
    elapsed_seconds: float

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / self.sample_rate


@dataclass(frozen=True)
class ModelDescriptor:
    selection: ModelSelection
    display_name: str
    runtime: str
    capabilities: frozenset[ModelCapability]


@dataclass(frozen=True)
class VoiceCatalog:
    named: tuple[NamedVoice, ...]
    default: VoiceSelection
    accepts_reference_audio: bool


@dataclass(frozen=True)
class PreparedArtifact:
    label: str
    path: Path


@dataclass(frozen=True)
class SetupReceipt:
    artifacts: tuple[PreparedArtifact, ...]


@dataclass(frozen=True)
class ModelCheck:
    name: str
    status: Literal["pass", "warn", "fail"]
    detail: str


@dataclass(frozen=True)
class ModelStatus:
    ready: bool
    checks: tuple[ModelCheck, ...]
    setup_hint: str | None = None


class UnsupportedCapability(ValueError):
    """Raised when a speech model cannot honor a requested capability."""


class SpeechModel(Protocol):
    @property
    def descriptor(self) -> ModelDescriptor: ...

    def setup(self, *, force: bool = False) -> SetupReceipt: ...

    def status(self) -> ModelStatus: ...

    def voice_catalog(self) -> VoiceCatalog: ...

    def synthesize(self, request: SynthesisRequest) -> Speech: ...
