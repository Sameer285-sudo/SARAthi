"""Speech-to-Text via OpenAI Whisper. Falls back to placeholder when no key."""
from __future__ import annotations

import io

from shared.config import settings

LANG_CODE = {"English": "en", "Telugu": "te", "Hindi": "hi"}


def transcribe_audio(audio_bytes: bytes, filename: str, language: str = "English") -> str:
    if not settings.openai_api_key:
        return "[STT unavailable — configure OPENAI_API_KEY to enable audio transcription]"
    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        lang_code = LANG_CODE.get(language, "en")
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename
        transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file, language=lang_code)
        return transcript.text.strip()
    except Exception as exc:
        return f"[Transcription error: {exc}]"


def detect_language_from_audio(audio_bytes: bytes, filename: str) -> str:
    if not settings.openai_api_key:
        return "English"
    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename
        transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file, response_format="verbose_json")
        detected = getattr(transcript, "language", "en")
        return {"te": "Telugu", "hi": "Hindi", "en": "English"}.get(detected, "English")
    except Exception:
        return "English"
