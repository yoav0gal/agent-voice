from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from agent_voice import kokoro as kokoro_module
from agent_voice.kokoro import KOKORO_MAX_PHONEMES, KokoroAdapter, _split_phonemes
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
        self.text = None

    def get_voices(self):
        return ["af_heart"]

    def create(self, text, voice, speed, lang):
        self.text = text
        self.speed = speed
        return np.zeros(24_000, dtype=np.float32), 24_000

    def create_chunks(self, text, voice, speed, lang):
        self.text = text
        self.speed = speed
        yield np.zeros(240, dtype=np.float32), 24_000
        yield np.ones(480, dtype=np.float32), 24_000


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


def test_streaming_preserves_model_chunks_and_post_processes_each(monkeypatch):
    model, runtime = fake_model(monkeypatch)
    tempo_factors = []

    def change_tempo(samples, _sample_rate, factor):
        tempo_factors.append(factor)
        return samples

    monkeypatch.setattr(kokoro_module, "change_tempo", change_tempo)

    chunks = list(model.synthesize_stream(SynthesisRequest("Stream me", speed=1.5)))

    assert [len(chunk.samples) for chunk in chunks] == [240, 480]
    assert runtime.speed == 1.0
    assert tempo_factors == [1.5, 1.5]


@pytest.mark.parametrize("speed", [0.49, 4.01])
def test_speed_outside_supported_range_is_rejected(monkeypatch, speed):
    model, _ = fake_model(monkeypatch)
    with pytest.raises(ValueError, match="between 0.5 and 4.0"):
        model.synthesize(SynthesisRequest("Invalid speed", speed=speed))


def test_kokoro_accepts_up_to_50_000_characters(monkeypatch):
    model, runtime = fake_model(monkeypatch)
    text = "a" * 50_000

    model.synthesize(SynthesisRequest(text))

    assert runtime.text == text
    with pytest.raises(ValueError, match="maximum 50,000 characters"):
        model.synthesize(SynthesisRequest(text + "a"))


def test_phoneme_splitter_preserves_long_spans_at_the_batch_boundary():
    phonemes = "a" * (KOKORO_MAX_PHONEMES - 1) + "." + "b" * (KOKORO_MAX_PHONEMES + 17)

    chunks = _split_phonemes(phonemes)

    assert "".join(chunks) == phonemes
    assert all(0 < len(chunk) <= KOKORO_MAX_PHONEMES for chunk in chunks)


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


def test_voice_catalog_groups_voices_under_supported_language_tags(monkeypatch):
    model, _ = fake_model(monkeypatch)

    catalog = model.voice_catalog()

    assert catalog.languages[0].tag == "en-us"
    assert catalog.languages[0].voices == (NamedVoice("af_heart"),)
    assert [language.tag for language in catalog.languages] == [
        "en-us",
        "en-gb",
        "ja",
        "cmn",
        "es",
        "fr-fr",
        "hi",
        "it",
        "pt-br",
    ]
