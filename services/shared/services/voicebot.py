"""Voicebot session logic — DB-persisted CallSession, supports web chat and Twilio IVR."""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from sqlalchemy.orm import Session

from shared.models import CallSession, GrievanceTicket
from shared.schemas import VoiceSessionResponse, VoiceTicketInfo, VoiceMessage
from shared.services import ai_service
from shared.services.call_centre import (
    assigned_team, classify_issue, next_action,
    resolution_eta, sentiment_label, summarize_transcript,
)

LanguageCode = Literal["English", "Telugu", "Hindi"]
LANGUAGE_OPTIONS: dict[int, LanguageCode] = {1: "English", 2: "Telugu", 3: "Hindi"}

LANGUAGE_PROMPTS: dict[str, dict[str, str]] = {
    "English": {
        "welcome": "Welcome to the PDS360 AI Call Centre. Press 1 for English, Press 2 for Telugu, Press 3 for Hindi.",
        "ready": "Thank you. Please describe your issue — I can help with FAQs, complaint registration, and status tracking.",
        "ticket": "I have created a support ticket for you.",
        "goodbye": "Thank you for contacting PDS360. Have a great day!",
    },
    "Telugu": {
        "welcome": "PDS360 AI కాల్ సెంటర్‌కు స్వాగతం. ఇంగ్లీష్ కోసం 1, తెలుగు కోసం 2, హిందీ కోసం 3 నొక్కండి.",
        "ready": "ధన్యవాదాలు. దయచేసి మీ సమస్య చెప్పండి.",
        "ticket": "మీ కోసం ఒక సపోర్ట్ టికెట్ సృష్టించాను.",
        "goodbye": "PDS360 ని సంప్రదించినందుకు ధన్యవాదాలు. శుభ దినం!",
    },
    "Hindi": {
        "welcome": "PDS360 AI कॉल सेंटर में आपका स्वागत है। अंग्रेज़ी के लिए 1, तेलुगु के लिए 2, हिंदी के लिए 3 दबाएँ।",
        "ready": "धन्यवाद। कृपया अपनी समस्या बताइए।",
        "ticket": "मैंने आपके लिए एक सपोर्ट टिकट बना दिया है।",
        "goodbye": "PDS360 से संपर्क करने के लिए धन्यवाद। शुभ दिन!",
    },
}

CALLER_LABELS = {"public": "Public User", "shop_owner": "Fair Price Shop Owner", "officer": "Government Officer"}


def _append(session: CallSession, speaker: str, text: str, db: Session) -> None:
    entries = list(session.transcript or [])
    entries.append({"speaker": speaker, "text": text})
    session.transcript = entries
    db.commit()


def _to_response(session: CallSession, agent_message: str, ticket: GrievanceTicket | None = None) -> VoiceSessionResponse:
    ticket_info = None
    if ticket:
        ticket_info = VoiceTicketInfo(ticket_id=ticket.ticket_id, category=ticket.category,
                                      priority=ticket.priority, assigned_team=ticket.assigned_team, status=ticket.status)
    elif session.ticket_id:
        ticket_info = VoiceTicketInfo(ticket_id=session.ticket_id, category="Support",
                                      priority="MEDIUM", assigned_team="Citizen Help Desk", status="OPEN")
    return VoiceSessionResponse(
        session_id=session.session_id, caller_name=session.caller_name, caller_type=session.caller_type,
        language=session.language, current_state=session.current_state, agent_message=agent_message,
        transcript=[VoiceMessage(speaker=m["speaker"], text=m["text"]) for m in (session.transcript or [])],
        sentiment_score=session.sentiment_score, sentiment_label=session.sentiment_label, created_ticket=ticket_info,
    )


def _create_ticket(db: Session, session: CallSession, utterance: str) -> GrievanceTicket:
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
    db.refresh(ticket)
    return ticket


def start_voice_session(db: Session, caller_name: str, caller_type: str, channel: str = "chat") -> VoiceSessionResponse:
    session = CallSession(session_id=str(uuid4()), channel=channel, caller_name=caller_name,
                          caller_type=caller_type, current_state="language_selection", transcript=[])
    db.add(session)
    db.commit()
    db.refresh(session)
    welcome = LANGUAGE_PROMPTS["English"]["welcome"]
    _append(session, "agent", welcome, db)
    return _to_response(session, welcome)


def choose_language(db: Session, session_id: str, language_option: int) -> VoiceSessionResponse:
    session = db.query(CallSession).filter(CallSession.session_id == session_id).first()
    if not session:
        raise ValueError(f"Session {session_id} not found")
    language = LANGUAGE_OPTIONS.get(language_option, "English")
    session.language = language
    session.current_state = "conversation"
    db.commit()
    ready = LANGUAGE_PROMPTS[language]["ready"]
    _append(session, "agent", ready, db)
    return _to_response(session, ready)


def process_voice_turn(db: Session, session_id: str, utterance: str) -> VoiceSessionResponse:
    session = db.query(CallSession).filter(CallSession.session_id == session_id).first()
    if not session:
        raise ValueError(f"Session {session_id} not found")
    language = session.language or "English"
    _append(session, "caller", utterance, db)
    score, label = ai_service.analyze_sentiment(utterance)
    session.sentiment_score = score
    session.sentiment_label = label
    db.commit()
    caller_label = CALLER_LABELS.get(session.caller_type, session.caller_type)
    ai_response = ai_service.generate_response(f"{caller_label}: {utterance}", language, session.caller_type)
    ticket = None
    if ai_service.needs_ticket(utterance, ai_response):
        ticket = _create_ticket(db, session, utterance)
        ticket_note = LANGUAGE_PROMPTS[language]["ticket"]
        final_message = (f"{ai_response} {ticket_note} Ticket ID: {ticket.ticket_id}. "
                         f"Assigned to {ticket.assigned_team}. Expected resolution in {ticket.resolution_eta_hours} hours.")
        session.current_state = "ticket_created"
    else:
        final_message = ai_response
        session.current_state = "conversation"
    db.commit()
    _append(session, "agent", final_message, db)
    return _to_response(session, final_message, ticket)
