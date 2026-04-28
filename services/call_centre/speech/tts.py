"""
Text-to-Speech module for PDS Call Centre.

Priority
--------
1. OpenAI TTS (tts-1)  — English only, high quality, requires OPENAI_API_KEY
2. gTTS (Google TTS)   — all 6 languages, free, requires internet
3. Silent placeholder  — returned when both engines fail (dev/offline mode)

Usage
-----
from call_centre.speech.tts import synthesize, get_prompt

result = synthesize("Your ration is available.", "Telugu")
# result.audio_bytes -> MP3 bytes
# result.method      -> "gtts" | "openai" | "silent"
"""
from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

# gTTS / BCP-47 language codes
LANG_CODES: dict[str, str] = {
    "English": "en",
    "Telugu":  "te",
    "Hindi":   "hi",
    "Kannada": "kn",
    "Tamil":   "ta",
    "Urdu":    "ur",
}

# Twilio <Say> / <Gather speech> BCP-47 codes
TWILIO_LANG_CODES: dict[str, str] = {
    "English": "en-IN",
    "Telugu":  "te-IN",
    "Hindi":   "hi-IN",
    "Kannada": "kn-IN",
    "Tamil":   "ta-IN",
    "Urdu":    "ur-PK",
}


@dataclass
class TTSResult:
    audio_bytes: bytes
    language: str
    method: str   # "openai" | "gtts" | "silent"
    format: str = "mp3"


# ── Engine implementations ────────────────────────────────────────────────────

def _openai_tts(text: str) -> TTSResult | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.audio.speech.create(model="tts-1", voice="nova", input=text[:4096])
        return TTSResult(audio_bytes=resp.content, language="English", method="openai")
    except Exception as exc:
        log.warning("OpenAI TTS failed: %s", exc)
        return None


def _gtts(text: str, language: str) -> TTSResult | None:
    try:
        from gtts import gTTS
        lang_code = LANG_CODES.get(language, "en")
        tts = gTTS(text=text, lang=lang_code, slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        return TTSResult(audio_bytes=buf.getvalue(), language=language, method="gtts")
    except Exception as exc:
        log.warning("gTTS failed (lang=%s): %s", language, exc)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def synthesize(text: str, language: str = "English") -> TTSResult:
    """
    Convert text to MP3 audio bytes.

    Tries OpenAI TTS first (English only), then gTTS for all languages,
    then returns a silent placeholder so callers never crash.
    """
    if language == "English":
        result = _openai_tts(text)
        if result:
            return result

    result = _gtts(text, language)
    if result:
        return result

    log.error("All TTS engines unavailable — returning silent placeholder")
    return TTSResult(audio_bytes=b"", language=language, method="silent")


# ── Pre-written IVR prompts (all 6 languages) ─────────────────────────────────

_PROMPTS: dict[str, dict[str, str]] = {
    "welcome": {
        "English": (
            "Welcome to P D S support system. "
            "Press 1 for Telugu. Press 2 for English. Press 3 for Hindi. "
            "Press 4 for Kannada. Press 5 for Tamil. Press 6 for Urdu."
        ),
        "Telugu":  "పి డి ఎస్ సహాయ వ్యవస్థకు స్వాగతం. మీ భాష ఎంచుకోండి.",
        "Hindi":   "पी डी एस सहायता प्रणाली में आपका स्वागत है। अपनी भाषा चुनें।",
        "Kannada": "ಪಿ ಡಿ ಎಸ್ ಬೆಂಬಲ ವ್ಯವಸ್ಥೆಗೆ ಸ್ವಾಗತ. ನಿಮ್ಮ ಭಾಷೆ ಆಯ್ಕೆಮಾಡಿ.",
        "Tamil":   "பி டி எஸ் உதவி அமைப்பிற்கு வரவேற்கிறோம். உங்கள் மொழியை தேர்ந்தெடுக்கவும்.",
        "Urdu":    "پی ڈی ایس سپورٹ سسٹم میں خوش آمدید۔ اپنی زبان منتخب کریں۔",
    },
    "ask_query": {
        "English": "How can I help you today? Please speak your query.",
        "Telugu":  "నేను మీకు ఎలా సహాయం చేయగలను? దయచేసి మీ ప్రశ్న చెప్పండి.",
        "Hindi":   "आज मैं आपकी कैसे सहायता कर सकता हूँ? कृपया अपना सवाल बोलें।",
        "Kannada": "ಇಂದು ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು? ದಯವಿಟ್ಟು ನಿಮ್ಮ ಪ್ರಶ್ನೆ ಹೇಳಿ.",
        "Tamil":   "இன்று நான் உங்களுக்கு எப்படி உதவ முடியும்? உங்கள் கேள்வியை சொல்லுங்கள்.",
        "Urdu":    "آج میں آپ کی کیا مدد کر سکتا ہوں؟ براہ کرم اپنا سوال بولیں۔",
    },
    "ticket_created": {
        "English": "Your complaint has been registered. Our team will contact you within 24 hours.",
        "Telugu":  "మీ ఫిర్యాదు నమోదైంది. మా బృందం 24 గంటలలో మీతో సంప్రదిస్తుంది.",
        "Hindi":   "आपकी शिकायत दर्ज की गई है। हमारी टीम 24 घंटे में आपसे संपर्क करेगी।",
        "Kannada": "ನಿಮ್ಮ ದೂರು ನೋಂದಾಯಿಸಲಾಗಿದೆ. ನಮ್ಮ ತಂಡ 24 ಗಂಟೆಗಳಲ್ಲಿ ನಿಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸುತ್ತದೆ.",
        "Tamil":   "உங்கள் புகார் பதிவு செய்யப்பட்டது. எங்கள் குழு 24 மணி நேரத்தில் தொடர்பு கொள்ளும்.",
        "Urdu":    "آپ کی شکایت درج کر لی گئی ہے۔ ہماری ٹیم 24 گھنٹوں میں رابطہ کرے گی۔",
    },
    "goodbye": {
        "English": "Thank you for calling PDS support. Goodbye!",
        "Telugu":  "పిడిఎస్ కి కాల్ చేసినందుకు ధన్యవాదాలు. వీడ్కోలు!",
        "Hindi":   "PDS को कॉल करने के लिए धन्यवाद। अलविदा!",
        "Kannada": "PDS ಗೆ ಕರೆ ಮಾಡಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದ. ವಿದಾಯ!",
        "Tamil":   "PDS ஐ அழைத்ததற்கு நன்றி. விடை!",
        "Urdu":    "PDS کو کال کرنے کا شکریہ۔ خدا حافظ!",
    },
    "invalid_input": {
        "English": "I didn't catch that. Please try again.",
        "Telugu":  "నేను అర్థం చేసుకోలేదు. దయచేసి మళ్ళీ ప్రయత్నించండి.",
        "Hindi":   "मुझे समझ नहीं आया। कृपया फिर से प्रयास करें।",
        "Kannada": "ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
        "Tamil":   "புரியவில்லை. தயவுசெய்து மீண்டும் முயற்சிக்கவும்.",
        "Urdu":    "سمجھ نہیں آیا۔ براہ کرم دوبارہ کوشش کریں۔",
    },
    "language_confirmed": {
        "English": "English selected.",
        "Telugu":  "తెలుగు ఎంపిక చేయబడింది.",
        "Hindi":   "हिंदी चुना गया।",
        "Kannada": "ಕನ್ನಡ ಆಯ್ಕೆ ಮಾಡಲಾಗಿದೆ.",
        "Tamil":   "தமிழ் தேர்ந்தெடுக்கப்பட்டது.",
        "Urdu":    "اردو منتخب کی گئی۔",
    },
}


def get_prompt(key: str, language: str = "English") -> str:
    """Return the pre-written IVR prompt text for a given key and language."""
    bucket = _PROMPTS.get(key, {})
    return bucket.get(language) or bucket.get("English", "")


def synthesize_prompt(key: str, language: str = "English") -> TTSResult:
    """Synthesize a pre-written IVR prompt directly to audio."""
    text = get_prompt(key, language)
    return synthesize(text, language)
