"""
Speech-to-Text module for the PDS Call Centre.

Pipeline
--------
1. Accept raw audio bytes + filename (format hint from extension).
2. Try OpenAI Whisper API if OPENAI_API_KEY is set.
3. Fall back to a deterministic simulation so the system works without an API key.

Output contract
---------------
transcribe(audio_bytes, filename, language) -> TranscriptResult
  .transcript      : str
  .confidence_score: float  (0.0 – 1.0)
  .language        : str    ("English" | "Telugu" | "Hindi" | "Kannada" | "Tamil" | "Urdu")
  .word_count      : int
  .duration_hint   : float  (estimated seconds — bytes / 16000 / 2 for 16-bit PCM)
  .source          : "whisper" | "simulation"
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

_LANG_CODE = {
    "English": "en", "Telugu": "te", "Hindi": "hi",
    "Kannada": "kn", "Tamil":  "ta", "Urdu":  "ur",
}
_CODE_LANG = {
    "en": "English", "te": "Telugu", "hi": "Hindi",
    "kn": "Kannada", "ta": "Tamil",  "ur": "Urdu",
}

# Simulation samples — cycled deterministically from audio hash
_SIM_SAMPLES = [
    ("My ration has not been distributed this month. I want to file a complaint.", "English", 0.91),
    ("Rice stock is not available at our FPS shop for the past two weeks.", "English", 0.88),
    ("నా రేషన్ కార్డు అప్‌డేట్ కాలేదు. దయచేసి సహాయం చేయండి.", "Telugu", 0.85),
    ("The supply delay is causing problems for our family please help.", "English", 0.87),
    ("मुझे अपने राशन कार्ड में सुधार करवाना है।", "Hindi", 0.83),
    ("I want to know when the wheat distribution will happen.", "English", 0.92),
    ("FPS shop was closed today. I couldn't collect my monthly entitlement.", "English", 0.89),
    ("Stock is available thank you for the update.", "English", 0.94),
    ("జిల్లాలో స్టాక్ అందుబాటులో లేదు. ఫిర్యాదు నమోదు చేయాలి.", "Telugu", 0.82),
    ("Complaint about fraud at FPS shop, owner demanding extra money.", "English", 0.86),
    ("ನಮ್ಮ ಪಡಿತರ ಅಂಗಡಿ ಇಂದು ಮುಚ್ಚಿದೆ. ದೂರು ದಾಖಲಿಸಬೇಕು.", "Kannada", 0.84),
    ("எங்கள் ரேஷன் கடை இன்று திறக்கவில்லை. புகார் செய்ய வேண்டும்.", "Tamil", 0.83),
    ("ہمارے راشن کی دکان آج بند ہے۔ شکایت درج کرنی ہے۔", "Urdu", 0.81),
]


@dataclass
class TranscriptResult:
    transcript: str
    confidence_score: float
    language: str
    word_count: int
    duration_hint: float
    source: str


def _estimate_duration(audio_bytes: bytes) -> float:
    """Rough estimate: assume 16-bit PCM at 16 kHz mono."""
    return round(len(audio_bytes) / (16000 * 2), 1)


def _simulation(audio_bytes: bytes, language: str) -> TranscriptResult:
    idx = int(hashlib.md5(audio_bytes[:64]).hexdigest(), 16) % len(_SIM_SAMPLES)
    text, detected_lang, conf = _SIM_SAMPLES[idx]
    use_lang = language if language not in ("auto", "") else detected_lang
    return TranscriptResult(
        transcript=text,
        confidence_score=conf,
        language=use_lang,
        word_count=len(text.split()),
        duration_hint=_estimate_duration(audio_bytes),
        source="simulation",
    )


def _whisper(audio_bytes: bytes, filename: str, language: str) -> TranscriptResult | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import io
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        lang_code = _LANG_CODE.get(language) if language not in ("auto", "") else None
        kwargs: dict = {"model": "whisper-1", "response_format": "verbose_json"}
        if lang_code:
            kwargs["language"] = lang_code
        result = client.audio.transcriptions.create(
            file=(filename, io.BytesIO(audio_bytes)),
            **kwargs,
        )
        detected = _CODE_LANG.get(getattr(result, "language", "en"), "English")
        text = result.text.strip()
        return TranscriptResult(
            transcript=text,
            confidence_score=0.95,
            language=language if language not in ("auto", "") else detected,
            word_count=len(text.split()),
            duration_hint=getattr(result, "duration", _estimate_duration(audio_bytes)),
            source="whisper",
        )
    except Exception as exc:
        log.warning("Whisper API failed: %s", exc)
        return None


def transcribe(audio_bytes: bytes, filename: str = "audio.wav", language: str = "auto") -> TranscriptResult:
    """
    Transcribe audio bytes to text.

    Parameters
    ----------
    audio_bytes : raw audio file bytes
    filename    : original filename (used as format hint for Whisper)
    language    : "English" | "Telugu" | "Hindi" | "auto"

    Returns
    -------
    TranscriptResult
    """
    result = _whisper(audio_bytes, filename, language)
    if result:
        log.info("STT via Whisper: %d words, lang=%s", result.word_count, result.language)
        return result
    result = _simulation(audio_bytes, language)
    log.info("STT via simulation: %d words, lang=%s", result.word_count, result.language)
    return result


def detect_language(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """Detect language from audio. Returns 'English' | 'Telugu' | 'Hindi'."""
    result = transcribe(audio_bytes, filename, language="auto")
    return result.language
