"""
Call Centre API router — production endpoints.

Endpoints
---------
POST /call                         Full pipeline (STT → sentiment → bot → ticket)
GET  /tickets                      List all tickets
GET  /tickets/{id}                 Get single ticket
PUT  /tickets/{id}/status          Update ticket status
GET  /analytics/overview           KPI dashboard
GET  /analytics/sentiment          Sentiment trend + distribution
GET  /analytics/tickets            Ticket breakdown charts
GET  /analytics/call-volume        Call volume forecast + peak hours
GET  /analytics/complaints         Complaint category trends
GET  /agents/performance           Agent scoring
GET  /notifications                Notification log
POST /notifications/test           Send a test notification
GET  /sla/breaches                 SLA breach report
GET  /bot/health                   PDSAI-Bot health passthrough

── IVR (Twilio) ──
GET  /ivr/tts                      TTS audio endpoint (gTTS/OpenAI) for <Play>
POST /ivr/incoming                 Step 1 — answer call, play language menu
POST /ivr/language-selection       Step 2 — DTMF → language → confirm
POST /ivr/process-query            Step 3 — speech → pipeline → response (loops)
POST /ivr/call-end                 Step 4 — hang up gracefully
GET  /ivr/config                   Twilio configuration status
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # services/

from shared.db import get_db
from shared.auth.dependencies import optional_current_user, CurrentUser
from shared.services.call_centre import (
    classify_issue, get_ticket_by_id, get_tickets, update_ticket_status,
)

from call_centre.sentiment.sentiment_model  import sentiment_analyzer
from call_centre.speech.speech_to_text      import transcribe
from call_centre.tickets.ticket_service     import (
    check_sla_breaches, create_ticket, get_agent_performance,
    get_notification_log, send_escalation_alert,
)
from call_centre.chatbot.pdsai_client       import send_message, get_bot_health
from call_centre.analytics.metrics          import (
    get_overview, get_sentiment_analytics, get_ticket_analytics,
)
from call_centre.analytics.forecasting      import (
    get_call_volume_forecast, get_peak_hour_distribution, get_complaint_trends,
)

log    = logging.getLogger(__name__)
router = APIRouter(tags=["Call Centre v2"])


# ── POST /call — full pipeline ─────────────────────────────────────────────────

@router.post("/call")
async def full_call_pipeline(
    audio_file:   UploadFile | None = File(default=None),
    text_input:   str  = Form(default=""),
    user_id:      str  = Form(default="anonymous"),
    caller_name:  str  = Form(default="Unknown Caller"),
    caller_type:  str  = Form(default="public"),
    language:     str  = Form(default="auto"),
    role:         str  = Form(default="citizen"),
    session_id:   str  = Form(default=""),
    district:     str  = Form(default=""),
    db: Session        = Depends(get_db),
):
    """
    Full AI pipeline:
      1. Audio → STT (or accept raw text_input)
      2. Sentiment analysis (ML)
      3. Forward to PDSAI-Bot → intent + response
      4. Auto-create ticket if complaint/negative sentiment
      5. Return complete response

    Accepts multipart/form-data with optional audio_file.
    If audio_file is omitted, text_input is used directly.
    """
    # 1. Speech-to-Text
    stt_result = None
    if audio_file:
        audio_bytes = await audio_file.read()
        stt_result  = transcribe(audio_bytes, audio_file.filename or "audio.wav", language)
        transcript  = stt_result.transcript
        detected_lang = stt_result.language
        confidence_score = stt_result.confidence_score
    elif text_input.strip():
        transcript       = text_input.strip()
        detected_lang    = language if language != "auto" else "English"
        confidence_score = 1.0
    else:
        raise HTTPException(status_code=422, detail="Provide audio_file or text_input.")

    # 2. Sentiment analysis (ML)
    sent_result = sentiment_analyzer.analyze(transcript)

    # 3. Forward to PDSAI-Bot
    bot_session = session_id or str(uuid4())
    bot_resp    = send_message(
        message=transcript,
        role=role,
        session_id=bot_session,
        user_id=user_id,
        language=detected_lang,
    )
    bot_text = bot_resp.get("response", "")
    intent   = bot_resp.get("intent", "general_query")

    # 4. Auto-ticket: complaint intent OR distressed/negative sentiment
    ticket_data = None
    auto_ticket = (
        intent in ("grievance", "delivery_status")
        or sent_result.score <= -0.25
        or any(w in transcript.lower() for w in ["complaint", "grievance", "fraud", "not available"])
    )
    if auto_ticket:
        category = classify_issue(transcript)
        ticket_data = create_ticket(
            db,
            transcript=transcript,
            sentiment_score=sent_result.score,
            sentiment_label=sent_result.label,
            category=category,
            caller_name=caller_name,
            caller_type=caller_type,
            language=detected_lang,
            channel="api_call",
            district=district,
        )
        log.info("Auto-ticket: %s | category=%s | priority=%s",
                 ticket_data["ticket_id"], category, ticket_data["priority"])

    return {
        "module":    "AI Call Centre",
        "call_id":   str(uuid4())[:8].upper(),
        "user_id":   user_id,
        "language":  detected_lang,
        "transcript": {
            "text":             transcript,
            "confidence_score": confidence_score,
            "source":           stt_result.source if stt_result else "text_input",
            "word_count":       len(transcript.split()),
        },
        "sentiment": {
            "score":    sent_result.score,
            "label":    sent_result.label,
            "keywords": sent_result.keywords,
            "method":   sent_result.method,
        },
        "chatbot": {
            "response":          bot_text,
            "intent":            intent,
            "intent_confidence": bot_resp.get("intent_confidence", 0.5),
            "source":            bot_resp.get("source", "unknown"),
            "suggestions":       bot_resp.get("suggestions", []),
            "session_id":        bot_resp.get("session_id", bot_session),
        },
        "ticket":      ticket_data,
        "ticket_created": ticket_data is not None,
    }


# ── Ticket endpoints (spec-compatible aliases) ─────────────────────────────────

@router.get("/tickets")
def list_tickets(
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(optional_current_user),
):
    return {"module": "AI Call Centre", "tickets": get_tickets(db, user)}


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    t = get_ticket_by_id(db, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"module": "AI Call Centre", "ticket": t}


@router.put("/tickets/{ticket_id}/status")
def set_ticket_status(ticket_id: str, body: dict, db: Session = Depends(get_db)):
    valid = {"OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"}
    status = (body.get("status") or "").upper()
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")
    t = update_ticket_status(db, ticket_id, status)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"module": "AI Call Centre", "ticket_id": ticket_id, "status": t.status}


# ── Analytics endpoints ────────────────────────────────────────────────────────

@router.get("/analytics/overview")
def analytics_overview(
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(optional_current_user),
):
    return get_overview(db, user)


@router.get("/analytics/sentiment")
def analytics_sentiment(
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(optional_current_user),
):
    return get_sentiment_analytics(db, user)


@router.get("/analytics/tickets")
def analytics_tickets(
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(optional_current_user),
):
    return get_ticket_analytics(db, user)


@router.get("/analytics/call-volume")
def analytics_call_volume(db: Session = Depends(get_db)):
    vol  = get_call_volume_forecast(db)
    peak = get_peak_hour_distribution(db)
    return {
        "module":      "Call Centre Analytics",
        "volume":      vol,
        "peak_hours":  peak,
    }


@router.get("/analytics/complaints")
def analytics_complaints(db: Session = Depends(get_db)):
    return get_complaint_trends(db)


# ── Agent performance ──────────────────────────────────────────────────────────

@router.get("/agents/performance")
def agent_performance(db: Session = Depends(get_db)):
    return {
        "module":  "AI Call Centre",
        "agents":  get_agent_performance(db),
        "team_count": 5,
        "total_agents": 6,
    }


# ── SLA breaches ───────────────────────────────────────────────────────────────

@router.get("/sla/breaches")
def sla_breaches(db: Session = Depends(get_db)):
    breaches = check_sla_breaches(db)
    return {
        "module":          "AI Call Centre",
        "breach_count":    len(breaches),
        "critical_count":  sum(1 for b in breaches if b["priority"] == "HIGH"),
        "breaches":        breaches,
    }


# ── Notifications ──────────────────────────────────────────────────────────────

@router.get("/notifications")
def notifications(limit: int = 50):
    return {
        "module":        "AI Call Centre",
        "notifications": get_notification_log(limit),
        "total":         len(get_notification_log(1000)),
    }


@router.post("/notifications/test")
def test_notification(body: dict):
    ticket_id = body.get("ticket_id", f"TKT-{str(uuid4())[:8].upper()}")
    note = send_escalation_alert(
        ticket_id,
        reason=body.get("reason", "Manual test escalation"),
        sentiment_score=body.get("sentiment_score", -0.80),
    )
    return {"module": "AI Call Centre", "notification": note}


# ── Bot health passthrough ─────────────────────────────────────────────────────

@router.get("/bot/health")
def bot_health():
    return get_bot_health()


# ── IVR: TTS audio endpoint ────────────────────────────────────────────────────

@router.get("/ivr/tts")
async def ivr_tts(text: str, language: str = "English"):
    """
    Generate speech audio for Twilio's <Play> tag.
    Twilio fetches this URL at call time to stream the audio.
    Returns audio/mpeg (MP3).
    """
    from call_centre.speech.tts import synthesize
    result = synthesize(text[:500], language)
    if not result.audio_bytes:
        raise HTTPException(status_code=503, detail="TTS generation failed — check gTTS/OpenAI config")
    return Response(content=result.audio_bytes, media_type="audio/mpeg")


# ── IVR: Step 1 — incoming call ────────────────────────────────────────────────

@router.post("/ivr/incoming")
async def ivr_incoming():
    """
    Twilio webhook for new inbound calls.
    Plays the 6-language selection menu and waits for a DTMF digit.
    Configure as the Voice Webhook in the Twilio console.
    """
    from call_centre.ivr.call_flow import welcome_twiml
    return Response(content=welcome_twiml(), media_type="application/xml")


# ── IVR: Step 2 — language selection ──────────────────────────────────────────

@router.post("/ivr/language-selection")
async def ivr_language_selection(request: Request):
    """
    Receives the DTMF digit from Twilio, stores the language on the call session,
    confirms the choice, then asks the caller to speak their query.
    """
    from call_centre.ivr.call_flow import language_confirmed_twiml, error_twiml
    from call_centre.ivr.dtmf_handler import digit_to_language
    from call_centre.telephony.twilio_client import set_language

    form     = await request.form()
    call_sid = str(form.get("CallSid", "dev"))
    digit    = str(form.get("Digits", ""))
    language = digit_to_language(digit)

    if not language:
        log.warning("Invalid DTMF digit '%s' from call %s", digit, call_sid)
        return Response(content=error_twiml("English"), media_type="application/xml")

    set_language(call_sid, language)
    return Response(content=language_confirmed_twiml(language), media_type="application/xml")


# ── IVR: Step 3 — process speech query ────────────────────────────────────────

@router.post("/ivr/process-query")
async def ivr_process_query(request: Request, db: Session = Depends(get_db)):
    """
    Receives SpeechResult from Twilio, runs the full AI pipeline
    (sentiment → PDSAI-Bot → auto-ticket), then plays back the response.
    Loops until the caller hangs up or is redirected to /ivr/call-end.
    """
    from call_centre.ivr.call_flow import (
        query_response_twiml, ticket_created_twiml,
        no_speech_twiml, error_twiml,
    )
    from call_centre.telephony.twilio_client import get_session

    form         = await request.form()
    call_sid     = str(form.get("CallSid", "dev"))
    speech_text  = str(form.get("SpeechResult", "")).strip()

    session  = get_session(call_sid)
    language = session.language
    session.touch()

    if not speech_text:
        return Response(content=no_speech_twiml(language), media_type="application/xml")

    session.transcript.append({"speaker": "caller", "text": speech_text})
    log.info("IVR query: call=%s lang=%s text=%r", call_sid, language, speech_text[:80])

    try:
        # Sentiment
        sent = sentiment_analyzer.analyze(speech_text)

        # Bot
        bot_resp = send_message(
            message=speech_text,
            role="citizen",
            session_id=session.session_id,
            user_id=call_sid,
            language=language,
        )
        bot_text = bot_resp.get("response", "I'm sorry, I could not process that. Please try again.")
        intent   = bot_resp.get("intent", "general_query")
        session.transcript.append({"speaker": "agent", "text": bot_text})

        # Auto-ticket
        auto_ticket = (
            intent in ("grievance", "delivery_status", "complaint_fraud")
            or sent.score <= -0.25
            or any(w in speech_text.lower() for w in ["complaint", "grievance", "fraud", "not available"])
        )

        if auto_ticket:
            category    = classify_issue(speech_text)
            ticket_data = create_ticket(
                db,
                transcript    = speech_text,
                sentiment_score = sent.score,
                sentiment_label = sent.label,
                category      = category,
                caller_name   = f"IVR Caller ({call_sid[:8]})",
                caller_type   = "public",
                language      = language,
                channel       = "ivr_call",
                district      = "",
            )
            ticket_id = ticket_data.get("ticket_id", "TKT-UNKNOWN")
            log.info("IVR auto-ticket: %s | %s | %s", ticket_id, category, language)
            return Response(content=ticket_created_twiml(ticket_id, language), media_type="application/xml")

        return Response(content=query_response_twiml(bot_text, language), media_type="application/xml")

    except Exception as exc:
        log.error("IVR pipeline error: %s", exc)
        return Response(content=error_twiml(language), media_type="application/xml")


# ── IVR: Step 4 — call end ─────────────────────────────────────────────────────

@router.post("/ivr/call-end")
async def ivr_call_end(request: Request):
    """Twilio status callback for call termination. Cleans up the session."""
    from call_centre.ivr.call_flow import goodbye_twiml
    from call_centre.telephony.twilio_client import end_session

    form     = await request.form()
    call_sid = str(form.get("CallSid", ""))
    if call_sid:
        session = end_session(call_sid)
        if session:
            log.info("IVR call ended: %s | turns=%d | lang=%s", call_sid, session.turn_count, session.language)

    language = str(form.get("language", "English"))
    return Response(content=goodbye_twiml(language), media_type="application/xml")


# ── IVR: configuration status ──────────────────────────────────────────────────

@router.get("/ivr/config")
def ivr_config():
    """Return current Twilio IVR configuration status (no secrets exposed)."""
    from call_centre.telephony.twilio_client import config_status
    cfg = config_status()
    base_url = os.getenv("PUBLIC_BASE_URL", "")
    return {
        "module":               "AI Call Centre IVR",
        "twilio_configured":    cfg["configured"],
        "account_sid_set":      cfg["account_sid_set"],
        "auth_token_set":       cfg["auth_token_set"],
        "phone_number":         cfg["phone_number"] or "not configured",
        "public_base_url":      cfg["public_base_url"] or "not configured",
        "active_ivr_sessions":  cfg["active_sessions"],
        "languages_supported":  ["Telugu", "English", "Hindi", "Kannada", "Tamil", "Urdu"],
        "webhooks": {
            "incoming":           f"{base_url}/api/call-centre/ivr/incoming",
            "language_selection": f"{base_url}/api/call-centre/ivr/language-selection",
            "process_query":      f"{base_url}/api/call-centre/ivr/process-query",
            "call_end":           f"{base_url}/api/call-centre/ivr/call-end",
        },
        "setup_instructions": [
            "1. Set TWILIO_ACCOUNT_SID in services/.env",
            "2. Set TWILIO_AUTH_TOKEN in services/.env",
            "3. Set TWILIO_PHONE_NUMBER (your Twilio number, e.g. +18xxxxxxxxx)",
            "4. Run: ngrok http 8005   →   copy the https URL",
            "5. Set PUBLIC_BASE_URL=https://xxxx.ngrok-free.app in services/.env",
            "6. In Twilio Console → Phone Numbers → your number:",
            "   Voice Webhook (HTTP POST): {PUBLIC_BASE_URL}/api/call-centre/ivr/incoming",
            "   Status Callback (HTTP POST): {PUBLIC_BASE_URL}/api/call-centre/ivr/call-end",
            "7. Restart the call_centre service and call your Twilio number",
        ],
    }
