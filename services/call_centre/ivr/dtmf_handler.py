"""
DTMF digit → language mapping for PDS IVR.

IVR menu
--------
Press 1 → Telugu
Press 2 → English
Press 3 → Hindi
Press 4 → Kannada
Press 5 → Tamil
Press 6 → Urdu
"""
from __future__ import annotations

DTMF_TO_LANGUAGE: dict[str, str] = {
    "1": "Telugu",
    "2": "English",
    "3": "Hindi",
    "4": "Kannada",
    "5": "Tamil",
    "6": "Urdu",
}

LANGUAGE_TO_DTMF: dict[str, str] = {v: k for k, v in DTMF_TO_LANGUAGE.items()}

# BCP-47 codes for Twilio <Gather input="speech"> and <Say>
TWILIO_SPEECH_LANG: dict[str, str] = {
    "English": "en-IN",
    "Telugu":  "te-IN",
    "Hindi":   "hi-IN",
    "Kannada": "kn-IN",
    "Tamil":   "ta-IN",
    "Urdu":    "ur-PK",
}

# Amazon Polly voices available in Twilio for Indian languages
# Use for <Say voice="..."> when gTTS <Play> is not preferred
TWILIO_POLLY_VOICE: dict[str, str] = {
    "English": "Polly.Aditi",   # Indian English
    "Hindi":   "Polly.Aditi",   # Hindi
    "Telugu":  "Polly.Kajal",   # fallback — Telugu not natively in Polly
    "Kannada": "Polly.Kajal",
    "Tamil":   "Polly.Kajal",
    "Urdu":    "Polly.Aditi",
}


def digit_to_language(digit: str) -> str | None:
    """Return language name for a DTMF digit, or None if unrecognised."""
    return DTMF_TO_LANGUAGE.get(digit.strip())


def twilio_speech_lang(language: str) -> str:
    """BCP-47 code for Twilio's <Gather input=speech> attribute."""
    return TWILIO_SPEECH_LANG.get(language, "en-IN")
