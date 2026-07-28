from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from agent_voice import kokoro as kokoro_module
from agent_voice.kokoro import KokoroAdapter
from agent_voice.model import (
    ModelSelection,
    NamedVoice,
    ReferenceVoice,
    SetupReceipt,
    SynthesisRequest,
    UnsupportedCapability,
)


class FakeKokoro:
    def __init__(self):
        self.speed = None

    def get_voices(self):
        return ["af_heart"]

    def create(self, text, voice, speed, lang):
        self.speed = speed
        return np.zeros(24_000, dtype=np.float32), 24_000


def fake_model(monkeypatch):
    runtime = FakeKokoro()
    model = KokoroAdapter(
        ModelSelection("kokoro", "int8"),
        runtime_factory=lambda model_path, voices_path: runtime,
    )
    monkeypatch.setattr(model, "setup", lambda **kwargs: SetupReceipt(()))
    return model, runtime


@pytest.mark.parametrize("speed", [0.5, 0.75, 1.0, 1.5, 2.0, 4.0])
def test_speed_uses_natural_synthesis_then_post_processing(monkeypatch, speed):
    model, runtime = fake_model(monkeypatch)
    tempo_factors = []

    def change_tempo(samples, sample_rate, factor):
        tempo_factors.append(factor)
        return samples

    monkeypatch.setattr(kokoro_module, "change_tempo", change_tempo)

    speech = model.synthesize(
        SynthesisRequest(
            "Tempo-adjusted speech",
            voice=NamedVoice("af_heart"),
            speed=speed,
            language="en-us",
        )
    )

    assert runtime.speed == 1.0
    assert tempo_factors == [speed]
    assert speech.duration_seconds == 1.0


@pytest.mark.parametrize("speed", [0.49, 4.01])
def test_speed_outside_supported_range_is_rejected(monkeypatch, speed):
    model, _ = fake_model(monkeypatch)
    with pytest.raises(ValueError, match="between 0.5 and 4.0"):
        model.synthesize(SynthesisRequest("Invalid speed", speed=speed))


def test_kokoro_rejects_reference_audio_through_the_model_interface(
    monkeypatch, tmp_path
):
    model, _ = fake_model(monkeypatch)

    with pytest.raises(UnsupportedCapability, match="named voices"):
        model.synthesize(
            SynthesisRequest(
                "Reference audio is not a Kokoro capability",
                voice=ReferenceVoice(Path(tmp_path / "voice.wav")),
            )
        )


def test_descriptor_separates_model_identity_from_variant():
    descriptor = KokoroAdapter(ModelSelection("kokoro", "fp16")).descriptor

    assert descriptor.selection.model_id == "kokoro"
    assert descriptor.selection.variant == "fp16"
    assert descriptor.display_name == "Kokoro-82M"
    assert descriptor.runtime == "kokoro-onnx"
