import tools.voice_input as voice_input


class _FakeSegment:
    def __init__(self, text):
        self.text = text


def test_transcribe_empty_bytes_returns_empty_string_without_loading_model(monkeypatch):
    def fail_if_called():
        raise AssertionError("should not load the model for empty audio")
    monkeypatch.setattr(voice_input, "_get_model", fail_if_called)

    assert voice_input.transcribe(b"") == ""
    assert voice_input.transcribe(None) == ""


def test_transcribe_joins_segments_into_clean_text(monkeypatch):
    class _FakeModel:
        def transcribe(self, audio, beam_size):
            return [_FakeSegment(" What is the weather "), _FakeSegment("like today? ")], None

    monkeypatch.setattr(voice_input, "_get_model", lambda: _FakeModel())

    result = voice_input.transcribe(b"fake wav bytes")

    assert result == "What is the weather like today?"


def test_transcribe_returns_empty_string_on_failure_not_exception(monkeypatch):
    def raise_error():
        raise RuntimeError("model failed to load")
    monkeypatch.setattr(voice_input, "_get_model", raise_error)

    assert voice_input.transcribe(b"fake wav bytes") == ""


def test_get_model_is_lazy_and_cached(monkeypatch):
    calls = []

    class _FakeModel:
        pass

    def fake_whisper_model(size, device, compute_type):
        calls.append((size, device, compute_type))
        return _FakeModel()

    monkeypatch.setattr(voice_input, "WhisperModel", fake_whisper_model)
    monkeypatch.setattr(voice_input, "_model", None)

    first = voice_input._get_model()
    second = voice_input._get_model()

    assert first is second
    assert len(calls) == 1
    assert calls[0] == (voice_input.MODEL_SIZE, voice_input.DEVICE, voice_input.COMPUTE_TYPE)
