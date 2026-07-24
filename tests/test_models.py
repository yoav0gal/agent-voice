from kokoro_cli.models import MODEL_ASSETS, model_paths


def test_default_model_is_compact_int8():
    model, voices = model_paths()
    assert model.name == "kokoro-v1.0.int8.onnx"
    assert voices.name == "voices-v1.0.bin"
    assert MODEL_ASSETS["int8"][1] < 100_000_000
    assert len(MODEL_ASSETS["int8"][2]) == 64


def test_unknown_model_is_rejected():
    try:
        model_paths("tiny")
    except ValueError as error:
        assert "Unknown model variant" in str(error)
    else:
        raise AssertionError("expected ValueError")
