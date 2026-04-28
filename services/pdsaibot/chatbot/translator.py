"""
Multilingual translation utilities for PDSAI-Bot.

Language detection: langdetect (offline, no API key)
Translation:        deep-translator via Google backend (no API key)

Both are optional — the bot degrades gracefully if either library is absent.
Supported languages: English, Telugu, Hindi, Tamil, Kannada, Malayalam, Urdu, Bengali, Marathi.
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)

# ISO 639-1 code → display name
LANG_NAMES: dict[str, str] = {
    "en": "English",
    "te": "Telugu",
    "hi": "Hindi",
    "ta": "Tamil",
    "kn": "Kannada",
    "ml": "Malayalam",
    "ur": "Urdu",
    "bn": "Bengali",
    "mr": "Marathi",
}
_NAME_TO_CODE: dict[str, str] = {v.lower(): k for k, v in LANG_NAMES.items()}

try:
    from langdetect import detect as _ld_detect
    _DETECT_OK = True
    log.info("langdetect available — auto language detection enabled")
except ImportError:
    _DETECT_OK = False
    log.info("langdetect not installed — pip install langdetect to enable auto-detection")

try:
    from deep_translator import GoogleTranslator as _GT
    _TRANSLATE_OK = True
    log.info("deep-translator available — auto translation enabled")
except ImportError:
    _TRANSLATE_OK = False
    log.info("deep-translator not installed — pip install deep-translator to enable translation")


def detect(text: str) -> str:
    """Return ISO 639-1 code ('te', 'hi', 'en', …) or 'en' on failure."""
    if not _DETECT_OK or not text.strip():
        return "en"
    try:
        code = _ld_detect(text)
        return code if code in LANG_NAMES else "en"
    except Exception:
        return "en"


def lang_name_to_code(name: str) -> str:
    """'Telugu' → 'te', 'te' → 'te', unknown → 'en'."""
    n = name.strip().lower()
    if len(n) == 2 and n in LANG_NAMES:
        return n
    return _NAME_TO_CODE.get(n, "en")


def to_english(text: str, src: str = "auto") -> str:
    """Translate text to English. Returns original on failure or if already English."""
    if not _TRANSLATE_OK or src == "en" or not text.strip():
        return text
    try:
        result = _GT(source=src, target="en").translate(text)
        return result or text
    except Exception as exc:
        log.debug("to_english failed (src=%s): %s", src, exc)
        return text


def from_english(text: str, target: str = "en") -> str:
    """Translate English text to target language. Returns original on failure."""
    if not _TRANSLATE_OK or target == "en" or not text.strip():
        return text
    try:
        result = _GT(source="en", target=target).translate(text)
        return result or text
    except Exception as exc:
        log.debug("from_english failed (tgt=%s): %s", target, exc)
        return text
