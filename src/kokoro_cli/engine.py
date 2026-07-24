from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .audio import change_tempo
from .models import model_paths, models_ready

MIN_SPEED = 0.5
MAX_SPEED = 4.0
KOKORO_MAX_SPEED = 2.0


@dataclass(frozen=True)
class Speech:
    samples: NDArray[np.floating]
    sample_rate: int
    elapsed_seconds: float

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / self.sample_rate


class SpeechEngine:
    """Loads Kokoro once and serializes inference for predictable local use."""

    def __init__(self, variant: str = "int8") -> None:
        if not models_ready(variant):
            raise FileNotFoundError(
                f"Kokoro model is missing. Run: kokoro setup --model {variant}"
            )
        from kokoro_onnx import Kokoro

        model, voices = model_paths(variant)
        self.variant = variant
        self._kokoro = Kokoro(str(model), str(voices))
        self._lock = threading.Lock()

    def voices(self) -> list[str]:
        return self._kokoro.get_voices()

    def synthesize(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang: str = "en-us",
    ) -> Speech:
        text = text.strip()
        if not text:
            raise ValueError("Text cannot be empty")
        if len(text) > 20_000:
            raise ValueError("Text is too long (maximum 20,000 characters per request)")
        if not MIN_SPEED <= speed <= MAX_SPEED:
            raise ValueError(f"Speed must be between {MIN_SPEED} and {MAX_SPEED}")
        if voice not in self.voices():
            raise ValueError(f"Unknown voice '{voice}'")

        started = time.perf_counter()
        synthesis_speed = min(speed, KOKORO_MAX_SPEED)
        with self._lock:
            samples, sample_rate = self._kokoro.create(
                text, voice=voice, speed=synthesis_speed, lang=lang
            )
        if speed > KOKORO_MAX_SPEED:
            samples = change_tempo(samples, sample_rate, speed / synthesis_speed)
        return Speech(samples, sample_rate, time.perf_counter() - started)
