"""Automated unit and integration tests for Voice (STT, TTS, Audio processing)."""

import asyncio
import io
import wave
from typing import Any
import httpx
import pytest

from app.api import voice as voice_api
from app.config import settings
from app.main import app
from app.services.voice import audio_processor, speech_to_text, text_to_speech
from app.services.voice.audio_processor import (
    AudioTooLargeError,
    AudioValidationError,
    UnsupportedAudioFormatError,
    detect_audio_format,
    validate_audio,
)
from app.services.voice.text_to_speech import SpeechAudio, split_text_into_chunks

_test_cookies = httpx.Cookies()


def run_request(
    method: str,
    path: str,
    *,
    cookie_jar: httpx.Cookies | None = None,
    **kwargs: Any,
) -> httpx.Response:
    jar = cookie_jar if cookie_jar is not None else _test_cookies

    async def perform() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies=jar) as client:
            response = await client.request(method, path, **kwargs)
            jar.update(response.cookies)
            return response

    return asyncio.run(perform())


@pytest.fixture(autouse=True)
def clean_cookies():
    _test_cookies.clear()
    yield
    _test_cookies.clear()


# Minimal valid WAV header (44 bytes standard PCM WAV)
def make_mock_wav_bytes() -> bytes:
    header = bytearray(b"RIFF")
    header.extend((36).to_bytes(4, "little"))
    header.extend(b"WAVEfmt ")
    header.extend((16).to_bytes(4, "little"))  # Subchunk1Size
    header.extend((1).to_bytes(2, "little"))   # AudioFormat (PCM)
    header.extend((1).to_bytes(2, "little"))   # NumChannels
    header.extend((16000).to_bytes(4, "little"))  # SampleRate
    header.extend((32000).to_bytes(4, "little"))  # ByteRate
    header.extend((2).to_bytes(2, "little"))   # BlockAlign
    header.extend((16).to_bytes(2, "little"))  # BitsPerSample
    header.extend(b"data")
    header.extend((0).to_bytes(4, "little"))   # Subchunk2Size
    return bytes(header)


# Minimal valid WebM header
def make_mock_webm_bytes() -> bytes:
    return b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01"


# Minimal valid MP3 header
def make_mock_mp3_bytes() -> bytes:
    return b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x64" * 10


def test_audio_format_detection():
    wav = make_mock_wav_bytes()
    assert detect_audio_format(wav) == "wav"

    webm = make_mock_webm_bytes()
    assert detect_audio_format(webm) == "webm"

    mp3 = make_mock_mp3_bytes()
    assert detect_audio_format(mp3) == "mp3"

    assert detect_audio_format(b"corrupted_garbage_bytes") is None


def test_audio_format_detection_accepts_browser_container_headers():
    assert detect_audio_format(b"\x00\x00\x1a\x45\xdf\xa3" + b"\x00" * 8) == "webm"
    assert detect_audio_format(b"\x00\x00\x00\x08free\x00\x00\x00\x08ftyp" + b"\x00" * 8) == "m4a"


def test_audio_validation_rejects_empty():
    with pytest.raises(AudioValidationError):
        validate_audio(b"")


def test_audio_validation_rejects_unsupported():
    with pytest.raises(UnsupportedAudioFormatError):
        validate_audio(b"not an audio file at all", filename="test.txt")


def test_audio_validation_rejects_oversized(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "max_audio_upload_mb", 1)
    large_bytes = b"0" * (2 * 1024 * 1024)
    with pytest.raises(AudioTooLargeError):
        validate_audio(large_bytes, filename="large.wav")


def test_transcribe_audio_endpoint_valid(monkeypatch: pytest.MonkeyPatch):
    async def mock_transcribe(*args, **kwargs):
        return "Hello MNEMORA, this is a test recording."

    monkeypatch.setattr(voice_api, "transcribe_audio", mock_transcribe)

    wav = make_mock_wav_bytes()
    response = run_request(
        "POST",
        "/api/v1/voice/transcribe",
        files={"audio": ("test.wav", wav, "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "Hello MNEMORA, this is a test recording."
    assert "test.wav" in data["filename"]


def test_transcribe_upload_endpoint_valid(monkeypatch: pytest.MonkeyPatch):
    async def mock_transcribe(*args, **kwargs):
        return "Uploaded lecture audio transcription."

    monkeypatch.setattr(voice_api, "transcribe_audio", mock_transcribe)

    mp3 = make_mock_mp3_bytes()
    response = run_request(
        "POST",
        "/api/v1/voice/transcribe-upload",
        files={"file": ("lecture.mp3", mp3, "audio/mp3")},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "Uploaded lecture audio transcription."


def test_transcribe_rejects_corrupted_audio():
    response = run_request(
        "POST",
        "/api/v1/voice/transcribe",
        files={"audio": ("corrupt.wav", b"not-a-wav-file", "audio/wav")},
    )
    assert response.status_code == 400


def test_transcribe_rejects_empty_file():
    response = run_request(
        "POST",
        "/api/v1/voice/transcribe",
        files={"audio": ("empty.wav", b"", "audio/wav")},
    )
    assert response.status_code == 400


def test_transcribe_api_failure_handled(monkeypatch: pytest.MonkeyPatch):
    async def fail_transcribe(*args, **kwargs):
        raise speech_to_text.STTUnavailableError("OpenAI Whisper service unreachable.")

    monkeypatch.setattr(voice_api, "transcribe_audio", fail_transcribe)

    wav = make_mock_wav_bytes()
    response = run_request(
        "POST",
        "/api/v1/voice/transcribe",
        files={"audio": ("test.wav", wav, "audio/wav")},
    )
    assert response.status_code == 503
    assert "unreachable" in response.json()["detail"].lower()


def test_openai_quota_error_is_actionable():
    error = type(
        "QuotaError",
        (),
        {"status_code": 429, "body": {"code": "insufficient_quota"}},
    )()

    mapped = speech_to_text._map_openai_error(error)

    assert isinstance(mapped, speech_to_text.STTRateLimitError)
    assert "quota" in str(mapped).lower()
    assert "google_api_key" in str(mapped).lower()


def test_transcribe_uses_gemini_when_openai_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    async def fail_openai(*args, **kwargs):
        raise speech_to_text.STTRateLimitError("OpenAI has no credits.")

    gemini_calls: list[str] = []

    async def mock_gemini(data: bytes, detected_format: str, language: str | None) -> str:
        gemini_calls.append(detected_format)
        return "Gemini transcript"

    monkeypatch.setattr(speech_to_text, "_get_openai_client", lambda: object())
    monkeypatch.setattr(speech_to_text, "_get_gemini_client", lambda: object())
    monkeypatch.setattr(speech_to_text, "_transcribe_with_openai", fail_openai)
    monkeypatch.setattr(speech_to_text, "_transcribe_with_gemini", mock_gemini)

    text = asyncio.run(
        speech_to_text.transcribe_audio(make_mock_wav_bytes(), filename="clip.wav")
    )

    assert text == "Gemini transcript"
    assert gemini_calls == ["wav"]


def test_transcribe_uses_gemini_without_openai_key(monkeypatch: pytest.MonkeyPatch):
    async def mock_gemini(data: bytes, detected_format: str, language: str | None) -> str:
        return "Gemini transcript"

    monkeypatch.setattr(speech_to_text, "_get_openai_client", lambda: None)
    monkeypatch.setattr(speech_to_text, "_get_gemini_client", lambda: object())
    monkeypatch.setattr(speech_to_text, "_transcribe_with_gemini", mock_gemini)

    text = asyncio.run(
        speech_to_text.transcribe_audio(make_mock_mp3_bytes(), filename="clip.mp3")
    )

    assert text == "Gemini transcript"


def test_tts_synthesize_endpoint_valid(monkeypatch: pytest.MonkeyPatch):
    async def mock_synthesize(text: str, voice: str | None = None, **kwargs) -> SpeechAudio:
        return SpeechAudio(b"\xff\xfb\x90\x64MOCK_MP3_STREAM", "audio/mpeg", "mp3")

    monkeypatch.setattr(voice_api, "synthesize_speech", mock_synthesize)

    response = run_request(
        "POST",
        "/api/v1/voice/speak",
        json={"text": "MNEMORA is ready to assist you.", "voice": "alloy"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert b"MOCK_MP3_STREAM" in response.content


def test_tts_endpoint_serves_wav_when_provider_returns_wav(monkeypatch: pytest.MonkeyPatch):
    async def mock_synthesize(text: str, voice: str | None = None, **kwargs) -> SpeechAudio:
        return SpeechAudio(make_mock_wav_bytes(), "audio/wav", "wav")

    monkeypatch.setattr(voice_api, "synthesize_speech", mock_synthesize)

    response = run_request(
        "POST",
        "/api/v1/voice/speak",
        json={"text": "Hello from Gemini.", "voice": "nova"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content[:4] == b"RIFF"


def test_tts_synthesize_rejects_empty_text():
    response = run_request(
        "POST",
        "/api/v1/voice/speak",
        json={"text": "   ", "voice": "alloy"},
    )
    assert response.status_code == 400 or response.status_code == 422


def test_tts_chunking_long_text():
    short_text = "This is a brief response."
    assert split_text_into_chunks(short_text, max_chars=100) == [short_text]

    long_text = "Sentence one. " * 300
    chunks = split_text_into_chunks(long_text, max_chars=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)


def test_gemini_pcm_audio_is_wrapped_as_wav():
    pcm = b"\x00\x00" * 480
    wav = text_to_speech._normalise_gemini_audio(pcm, "audio/L16;codec=pcm;rate=24000")

    assert wav[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav), "rb") as wav_file:
        assert wav_file.getframerate() == 24000
        assert wav_file.getnchannels() == 1
        assert wav_file.getnframes() == 480


def test_wav_chunks_are_merged_into_one_file():
    first = text_to_speech._pcm_to_wav(b"\x01\x00" * 10)
    second = text_to_speech._pcm_to_wav(b"\x02\x00" * 10)

    merged = text_to_speech._merge_wav_chunks([first, second])

    with wave.open(io.BytesIO(merged), "rb") as wav_file:
        assert wav_file.getnframes() == 20


def test_tts_uses_gemini_when_openai_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    async def fail_openai(*args, **kwargs) -> bytes:
        raise text_to_speech.TTSRateLimitError("OpenAI has no credits.")

    async def mock_gemini(chunks: list[str], voice: str) -> bytes:
        return text_to_speech._pcm_to_wav(b"\x00\x00" * 240)

    monkeypatch.setattr(text_to_speech, "_get_openai_client", lambda: object())
    monkeypatch.setattr(text_to_speech, "_get_gemini_client", lambda: object())
    monkeypatch.setattr(text_to_speech, "_synthesize_with_openai", fail_openai)
    monkeypatch.setattr(text_to_speech, "_synthesize_with_gemini", mock_gemini)

    result = asyncio.run(text_to_speech.synthesize_speech("Hello there.", voice="nova"))

    assert isinstance(result, SpeechAudio)
    assert result.media_type == "audio/wav"
    assert result.data[:4] == b"RIFF"


def test_voice_settings_get_and_update():
    get_resp = run_request("GET", "/api/v1/voice/settings")
    assert get_resp.status_code == 200
    settings_data = get_resp.json()
    assert "available_voices" in settings_data
    assert "alloy" in settings_data["available_voices"]

    put_resp = run_request(
        "PUT",
        "/api/v1/voice/settings",
        json={"default_voice": "nova", "voice_enabled": True},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["default_voice"] == "nova"
