"""
TwiML builders for the PDS IVR call flow.

Each function returns an XML string ready to be sent as the HTTP response
to Twilio with Content-Type: application/xml.

Flow
----
1. Twilio calls POST /ivr/incoming
   → welcome_twiml()         play multilingual menu, gather 1 digit

2. Twilio posts digit to POST /ivr/language-selection
   → language_confirmed_twiml()   confirm language, gather speech

3. Twilio posts SpeechResult to POST /ivr/process-query  (loops)
   → query_response_twiml()       play AI response, gather next query
   → ticket_created_twiml()       if ticket auto-created

4. Call ends → POST /ivr/call-end
   → goodbye_twiml()
"""
from __future__ import annotations

import os
from urllib.parse import quote

from .dtmf_handler import twilio_speech_lang

_BASE = os.getenv("PUBLIC_BASE_URL", "http://localhost:8005")


def _tts_url(text: str, language: str = "English") -> str:
    """Backend endpoint that streams gTTS audio — Twilio uses <Play> to fetch it."""
    return f"{_BASE}/api/call-centre/ivr/tts?text={quote(text)}&language={quote(language)}"


# ── Step 1: Incoming call ─────────────────────────────────────────────────────

def welcome_twiml() -> str:
    """Answer the call and play the 6-language selection menu."""
    action = f"{_BASE}/api/call-centre/ivr/language-selection"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather numDigits="1" action="{action}" method="POST" timeout="12">
    <Say language="en-IN" voice="Polly.Aditi">
      Welcome to P D S support system.
      Press 1 for Telugu.
      Press 2 for English.
      Press 3 for Hindi.
      Press 4 for Kannada.
      Press 5 for Tamil.
      Press 6 for Urdu.
    </Say>
  </Gather>
  <Say language="en-IN">We did not receive your selection. Please call again. Thank you.</Say>
  <Hangup/>
</Response>"""


# ── Step 2: Language confirmed ────────────────────────────────────────────────

def language_confirmed_twiml(language: str) -> str:
    """Confirm the chosen language and ask for the caller's query."""
    action      = f"{_BASE}/api/call-centre/ivr/process-query"
    speech_lang = twilio_speech_lang(language)
    confirm_url = _tts_url(f"Language selected: {language}.", language)
    ask_url     = _tts_url("How can I help you today? Please speak your query after the beep.", language)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Play>{confirm_url}</Play>
  <Gather input="speech" language="{speech_lang}" action="{action}" method="POST"
          speechTimeout="4" timeout="10">
    <Play>{ask_url}</Play>
  </Gather>
  <Redirect method="POST">{_BASE}/api/call-centre/ivr/process-query</Redirect>
</Response>"""


# ── Step 3a: Normal AI response ───────────────────────────────────────────────

def query_response_twiml(response_text: str, language: str) -> str:
    """Play the bot's response and listen for the next query."""
    action      = f"{_BASE}/api/call-centre/ivr/process-query"
    speech_lang = twilio_speech_lang(language)
    resp_url    = _tts_url(response_text, language)
    follow_url  = _tts_url("Do you have another question? Please speak after the beep.", language)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Play>{resp_url}</Play>
  <Gather input="speech" language="{speech_lang}" action="{action}" method="POST"
          speechTimeout="4" timeout="12">
    <Play>{follow_url}</Play>
  </Gather>
  <Redirect method="POST">{_BASE}/api/call-centre/ivr/call-end</Redirect>
</Response>"""


# ── Step 3b: Ticket created ───────────────────────────────────────────────────

def ticket_created_twiml(ticket_id: str, language: str) -> str:
    """Confirm ticket creation and ask for another query."""
    action      = f"{_BASE}/api/call-centre/ivr/process-query"
    speech_lang = twilio_speech_lang(language)
    msg = (
        f"Your complaint has been registered. "
        f"Your ticket ID is {ticket_id}. "
        f"Our support team will contact you within 24 hours."
    )
    resp_url   = _tts_url(msg, language)
    follow_url = _tts_url("Do you have another question?", language)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Play>{resp_url}</Play>
  <Gather input="speech" language="{speech_lang}" action="{action}" method="POST"
          speechTimeout="4" timeout="10">
    <Play>{follow_url}</Play>
  </Gather>
  <Redirect method="POST">{_BASE}/api/call-centre/ivr/call-end</Redirect>
</Response>"""


# ── Step 4: Call end ──────────────────────────────────────────────────────────

def goodbye_twiml(language: str = "English") -> str:
    bye_url = _tts_url("Thank you for calling PDS support. Goodbye!", language)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Play>{bye_url}</Play>
  <Hangup/>
</Response>"""


# ── Error / retry ─────────────────────────────────────────────────────────────

def error_twiml(language: str = "English") -> str:
    err_url = _tts_url("I'm sorry, I encountered an error. Please try again.", language)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Play>{err_url}</Play>
  <Redirect method="POST">{_BASE}/api/call-centre/ivr/incoming</Redirect>
</Response>"""


def no_speech_twiml(language: str = "English") -> str:
    url = _tts_url("I didn't catch that. Please speak clearly after the beep.", language)
    action      = f"{_BASE}/api/call-centre/ivr/process-query"
    speech_lang = twilio_speech_lang(language)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather input="speech" language="{speech_lang}" action="{action}" method="POST"
          speechTimeout="4" timeout="10">
    <Play>{url}</Play>
  </Gather>
  <Redirect method="POST">{_BASE}/api/call-centre/ivr/call-end</Redirect>
</Response>"""
