from __future__ import annotations

import threading

import numpy as np
import pytest

from kokoro_cli import engine as engine_module
from kokoro_cli.engine import SpeechEngine


class FakeKokoro:
    def __init__(self):
        self.speed = None

    def get_voices(self):
        return ["af_heart"]

    def create(self, text, voice, speed, lang):
        self.speed = speed
        return np.zeros(24_000, dtype=np.float32), 24_000


def fake_engine():
    engine = object.__new__(SpeechEngine)
    engine.variant = "int8"
    engine._kokoro = FakeKokoro()
    engine._lock = threading.Lock()
    return engine


def test_speed_above_native_limit_uses_post_synthesis_tempo(monkeypatch):
    engine = fake_engine()
    tempo_factors = []

    def change_tempo(samples, sample_rate, factor):
        tempo_factors.append(factor)
        return samples[::2]

    monkeypatch.setattr(engine_module, "change_tempo", change_tempo)

    speech = engine.synthesize("Fast speech", speed=4.0)

    assert engine._kokoro.speed == 2.0
    assert tempo_factors == [2.0]
    assert speech.duration_seconds == 0.5


@pytest.mark.parametrize("speed", [0.49, 4.01])
def test_speed_outside_supported_range_is_rejected(speed):
    with pytest.raises(ValueError, match="between 0.5 and 4.0"):
        fake_engine().synthesize("Invalid speed", speed=speed)
