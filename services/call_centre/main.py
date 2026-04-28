"""
Call Centre Microservice — port 8005
AI-enabled multilingual call centre: sessions, tickets, audio STT, Twilio IVR, live WebSocket metrics.

v2 additions (modular):
  POST /call                  Full pipeline (STT → ML sentiment → PDSAI-Bot → auto-ticket)
  GET  /tickets               Ticket list (spec alias)
  PUT  /tickets/{id}/status   Status update (spec alias)
  GET  /analytics/overview    KPI dashboard
  GET  /analytics/sentiment   Sentiment trend + distribution
  GET  /analytics/tickets     Ticket breakdown charts
  GET  /analytics/call-volume Volume forecast + peak hours
  GET  /analytics/complaints  Category trend (stacked bar)
  GET  /agents/performance    Agent scoring
  GET  /sla/breaches          SLA breach report
  GET  /notifications         Notification simulation log
"""
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from shared.config import settings
from shared.db import Base, SessionLocal, engine, get_db
from shared.models import CallSession, GrievanceTicket
from shared.schemas import (
    AudioTranscriptResponse,
    TicketStatusUpdateRequest,
    VoiceLanguageSelectionRequest,
    VoiceSessionStartRequest,
    VoiceTurnRequest,
    VoiceTicketInfo,
)
from shared.seed import seed_data
from shared.services import ai_service
from shared.services.call_centre import (
    assigned_team, classify_issue, get_dashboard, get_live_metrics,
    get_summary, get_ticket_by_id, get_tickets, next_action,
    resolution_eta, sentiment_label, summarize_transcript, update_ticket_status,
)
from shared.services.stt_service import detect_language_from_audio, transcribe_audio
from shared.services.voicebot import choose_language, process_voice_turn, start_voice_session

try:
    import importlib.util as _ilu
    _routes_path = Path(__file__).resolve().parent / "api" / "routes.py"
    _spec = _ilu.spec_from_file_location("call_centre_routes", _routes_path)
    _mod  = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    v2_router = _mod.router
    _v2_ok = True
except Exception as _v2_err:
    import traceback as _tb
    _tb.print_exc()
    v2_router = None
    _v2_ok = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()
    yield


app = FastAPI(title="PDS360 — Call Centre Service", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# v2 modular router — adds /call, /analytics/*, /agents, /sla, /notifications
if _v2_ok and v2_router is not None:
    app.include_router(v2_router, prefix="/api/call-centre")


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "call_centre", "port": 8005}


# ── Tickets ────────────────────────────────────────────────────────────────────

@app.get("/api/call-centre/tickets")
def tickets(db: Session = Depends(get_db)):
    return {"module": "AI-enabled Call Centre", "tickets": get_tickets(db)}


@app.patch("/api/call-centre/tickets/{ticket_id}/status")
def update_status(ticket_id: str, body: TicketStatusUpdateRequest, db: Session = Depends(get_db)):
    valid = {"OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"}
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of {valid}")
    ticket = update_ticket_status(db, ticket_id, body.status)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"module": "AI-enabled Call Centre", "ticket_id": ticket_id, "status": ticket.status}


@app.get("/api/call-centre/tickets/{ticket_id}")
def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    ticket = get_ticket_by_id(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"module": "AI-enabled Call Centre", "ticket": ticket}


# ── Dashboard / summary ────────────────────────────────────────────────────────

@app.get("/api/call-centre/summary")
def summary(db: Session = Depends(get_db)):
    return {"module": "AI-enabled Call Centre", "summary": get_summary(db)}


@app.get("/api/call-centre/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return {"module": "AI-enabled Call Centre", "dashboard": get_dashboard(db)}


@app.get("/api/call-centre/live-metrics")
def live_metrics(db: Session = Depends(get_db)):
    return {"module": "AI-enabled Call Centre", "metrics": get_live_metrics(db)}


# ── Chatbot / voice session ────────────────────────────────────────────────────

@app.post("/api/call-centre/voice/session/start")
def start_session(payload: VoiceSessionStartRequest, db: Session = Depends(get_db)):
    return {"module": "AI-enabled Call Centre",
            "session": start_voice_session(db, payload.caller_name, payload.caller_type, payload.source_channel)}


@app.post("/api/call-centre/voice/session/language")
def set_language(payload: VoiceLanguageSelectionRequest, db: Session = Depends(get_db)):
    return {"module": "AI-enabled Call Centre", "session": choose_language(db, payload.session_id, payload.language_option)}


@app.post("/api/call-centre/voice/session/message")
def process_message(payload: VoiceTurnRequest, db: Session = Depends(get_db)):
    return {"module": "AI-enabled Call Centre", "session": process_voice_turn(db, payload.session_id, payload.utterance)}


# ── Audio upload + STT ─────────────────────────────────────────────────────────

@app.post("/api/call-centre/audio/transcribe", response_model=AudioTranscriptResponse)
async def transcribe_audio_upload(
    file: UploadFile = File(...),
    language: str = Form(default="auto"),
    caller_name: str = Form(default="Unknown Caller"),
    caller_type: str = Form(default="public"),
    db: Session = Depends(get_db),
):
    audio_bytes = await file.read()
    detected_lang = detect_language_from_audio(audio_bytes, file.filename or "audio.wav") if language == "auto" else language
    transcript = transcribe_audio(audio_bytes, file.filename or "audio.wav", detected_lang)
    score, label = ai_service.analyze_sentiment(transcript)
    ticket = None
    if ai_service.needs_ticket(transcript, ""):
        ticket_id = f"TKT-{str(uuid4())[:8].upper()}"
        category = classify_issue(transcript)
        priority = "HIGH" if score <= -0.45 else "MEDIUM"
        team = assigned_team(category)
        eta = resolution_eta(priority, category)
        db_ticket = GrievanceTicket(
            ticket_id=ticket_id, source_channel="audio_upload",
            caller_name=caller_name, caller_type=caller_type,
            language=detected_lang, category=category, priority=priority,
            sentiment_score=score, sentiment_label=label,
            transcript=transcript, summary=summarize_transcript(transcript, category),
            assigned_team=team, next_action=next_action(category, priority),
            resolution_eta_hours=eta, status="OPEN",
        )
        db.add(db_ticket)
        db.commit()
        ticket = VoiceTicketInfo(ticket_id=ticket_id, category=category, priority=priority, assigned_team=team, status="OPEN")
    return AudioTranscriptResponse(transcript=transcript, language_detected=detected_lang,
                                   sentiment_score=score, sentiment_label=label, created_ticket=ticket)


# ── Twilio IVR webhooks ────────────────────────────────────────────────────────

LANG_MAP = {"1": "English", "2": "Telugu", "3": "Hindi"}
TTS_LANG = {"English": "en-IN", "Telugu": "te-IN", "Hindi": "hi-IN"}

WELCOME_MSG = ("Welcome to the PDS360 AI Call Centre. "
               "For English, press 1. Telugu lo matlaadataniki 2 press cheyyandi. "
               "Hindi mein baat karne ke liye 3 dabaye.")
READY_MSG = {
    "English": "Thank you. Please describe your issue after the beep.",
    "Telugu": "ధన్యవాదాలు. బీప్ తర్వాత మీ సమస్య చెప్పండి.",
    "Hindi": "धन्यवाद। बीप के बाद अपनी समस्या बताइए।",
}
TICKET_MSG = {
    "English": "I have created a support ticket {ticket_id}. You will receive an update within {eta} hours.",
    "Telugu": "సపోర్ట్ టికెట్ {ticket_id} సృష్టించాను. {eta} గంటల్లో అప్‌డేట్ వస్తుంది.",
    "Hindi": "सपोर्ट टिकट {ticket_id} बनाया। {eta} घंटे में अपडेट मिलेगा।",
}


def _twiml(xml: str) -> Response:
    return Response(content=xml, media_type="application/xml")


def _gather(say: str, action: str, lang: str, input_type: str = "speech dtmf", num_digits: int | None = None) -> str:
    lc = TTS_LANG.get(lang, "en-IN")
    d = f' numDigits="{num_digits}"' if num_digits else ""
    sa = ' speechTimeout="auto" timeout="8"' if "speech" in input_type else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Gather input="{input_type}" action="{action}" method="POST"{d}{sa} language="{lc}">'
            f'<Say language="{lc}">{say}</Say></Gather>'
            f'<Say language="{lc}">We did not receive any input. Goodbye.</Say><Hangup/></Response>')


def _say_gather(say: str, action: str, lang: str) -> str:
    lc = TTS_LANG.get(lang, "en-IN")
    return (f'<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Say language="{lc}">{say}</Say>'
            f'<Gather input="speech dtmf" action="{action}" method="POST" speechTimeout="auto" timeout="8" language="{lc}">'
            f'<Say language="{lc}">Please speak after the beep.</Say></Gather><Hangup/></Response>')


def _say_hangup(say: str, lang: str = "English") -> str:
    lc = TTS_LANG.get(lang, "en-IN")
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Say language="{lc}">{say}</Say><Hangup/></Response>'


def _get_or_create_session(db: Session, call_sid: str, from_number: str) -> CallSession:
    session = db.query(CallSession).filter(CallSession.twilio_call_sid == call_sid).first()
    if not session:
        session = CallSession(session_id=str(uuid4()), twilio_call_sid=call_sid, channel="twilio",
                              caller_name=from_number or "Unknown", caller_type="public",
                              caller_phone=from_number, current_state="language_selection", transcript=[])
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def _append_twilio(session: CallSession, speaker: str, text: str, db: Session) -> None:
    entries = list(session.transcript or [])
    entries.append({"speaker": speaker, "text": text, "ts": datetime.utcnow().isoformat()})
    session.transcript = entries
    db.commit()


def _create_twilio_ticket(db: Session, session: CallSession, utterance: str) -> GrievanceTicket:
    ticket_id = f"TKT-{str(uuid4())[:8].upper()}"
    category = classify_issue(utterance)
    score = session.sentiment_score or -0.3
    priority = "HIGH" if score <= -0.45 else "MEDIUM"
    team = assigned_team(category)
    eta = resolution_eta(priority, category)
    ticket = GrievanceTicket(
        ticket_id=ticket_id, source_channel=session.channel,
        caller_name=session.caller_name, caller_type=session.caller_type,
        language=session.language or "English", category=category, priority=priority,
        sentiment_score=score, sentiment_label=sentiment_label(score),
        transcript=utterance, summary=summarize_transcript(utterance, category),
        assigned_team=team, next_action=next_action(category, priority),
        resolution_eta_hours=eta, status="OPEN",
    )
    db.add(ticket)
    session.ticket_id = ticket_id
    db.commit()
    return ticket


@app.post("/api/twilio/voice")
async def inbound_call(request: Request, CallSid: str = Form(default=""), From: str = Form(default=""),
                       db: Session = Depends(get_db)):
    session = _get_or_create_session(db, CallSid, From)
    base = settings.public_base_url
    action = f"{base}/api/twilio/voice/language?session_id={session.session_id}"
    return _twiml(_gather(WELCOME_MSG, action, "English", input_type="dtmf", num_digits=1))


@app.post("/api/twilio/voice/language")
async def language_selection(request: Request, session_id: str, Digits: str = Form(default="1"),
                              db: Session = Depends(get_db)):
    session = db.query(CallSession).filter(CallSession.session_id == session_id).first()
    if not session:
        return _twiml(_say_hangup("Session not found. Goodbye."))
    language = LANG_MAP.get(Digits, "English")
    session.language = language
    session.current_state = "conversation"
    db.commit()
    ready = READY_MSG[language]
    _append_twilio(session, "agent", ready, db)
    action = f"{settings.public_base_url}/api/twilio/voice/respond?session_id={session_id}"
    return _twiml(_gather(ready, action, language))


@app.post("/api/twilio/voice/respond")
async def voice_respond(request: Request, session_id: str,
                         SpeechResult: str = Form(default=""), Digits: str = Form(default=""),
                         db: Session = Depends(get_db)):
    session = db.query(CallSession).filter(CallSession.session_id == session_id).first()
    if not session:
        return _twiml(_say_hangup("Session not found. Goodbye."))
    language = session.language or "English"
    utterance = SpeechResult.strip() or Digits.strip()
    if not utterance:
        retry = {"English": "I didn't catch that. Please speak again.",
                 "Telugu": "నేను వినలేదు. దయచేసి మళ్ళీ చెప్పండి.",
                 "Hindi": "मुझे सुनाई नहीं दिया। कृपया फिर से बोलें।"}[language]
        action = f"{settings.public_base_url}/api/twilio/voice/respond?session_id={session_id}"
        return _twiml(_gather(retry, action, language))
    _append_twilio(session, "caller", utterance, db)
    score, label = ai_service.analyze_sentiment(utterance)
    session.sentiment_score = score
    session.sentiment_label = label
    db.commit()
    ai_response = ai_service.generate_response(utterance, language, session.caller_type)
    ticket = None
    if ai_service.needs_ticket(utterance, ai_response):
        ticket = _create_twilio_ticket(db, session, utterance)
    if ticket:
        ticket_note = TICKET_MSG[language].format(ticket_id=ticket.ticket_id, eta=ticket.resolution_eta_hours)
        full_response = f"{ai_response} {ticket_note}"
    else:
        full_response = ai_response
    _append_twilio(session, "agent", full_response, db)
    action = f"{settings.public_base_url}/api/twilio/voice/respond?session_id={session_id}"
    return _twiml(_say_gather(full_response, action, language))


@app.post("/api/twilio/voice/end")
async def call_ended(request: Request, CallSid: str = Form(default=""), CallDuration: str = Form(default="0"),
                     db: Session = Depends(get_db)):
    session = db.query(CallSession).filter(CallSession.twilio_call_sid == CallSid).first()
    if session:
        session.ended_at = datetime.utcnow()
        try:
            session.duration_seconds = int(CallDuration)
        except ValueError:
            pass
        session.current_state = "ended"
        db.commit()
    return Response(content="", status_code=204)


# ── WebSocket — live metrics ───────────────────────────────────────────────────

@app.websocket("/api/call-centre/ws/live")
async def websocket_live(websocket: WebSocket, db: Session = Depends(get_db)):
    await websocket.accept()
    try:
        while True:
            metrics = get_live_metrics(db)
            await websocket.send_text(metrics.model_dump_json())
            await asyncio.sleep(4)
    except (WebSocketDisconnect, Exception):
        pass


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=True)
