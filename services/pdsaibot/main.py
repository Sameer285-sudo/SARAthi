"""
PDSAIBot Microservice — port 8004
Hybrid NLU (Rasa/sklearn) + LangChain + FastAPI chatbot for PDS operations.
"""
from __future__ import annotations

import sys
import uuid
import logging
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import re
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from shared.db import Base, SessionLocal, engine
from shared.seed import seed_data

from models.schemas import ChatRequest, ChatResponse, GrievanceRequest, GrievanceResponse
from chatbot.router import process_message
from chatbot.memory import memory
from chatbot.langchain_agent import langchain_agent, fetch_stock_data, fetch_anomaly_data

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()
    log.info("PDSAIBot started — LLM ready: %s", langchain_agent.is_llm_ready)
    yield
    log.info("PDSAIBot shutting down — active sessions: %d", memory.session_count())


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PDS360 — PDSAIBot Service",
    version="2.0.0",
    description="Hybrid Rasa NLU + LangChain chatbot for Public Distribution System operations",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "pdsaibot",
        "port": 8004,
        "llm_ready": langchain_agent.is_llm_ready,
        "active_sessions": memory.session_count(),
    }


# ── Primary chat endpoint ─────────────────────────────────────────────────────

@app.post("/api/bot/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main conversational endpoint.
    Accepts a message and optional session_id for multi-turn context.
    """
    try:
        return await process_message(request)
    except Exception as exc:
        log.exception("Chat pipeline error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Bot error: {exc}")


# ── Backward-compatible legacy endpoint ──────────────────────────────────────

@app.post("/api/bot/query")
async def query_bot_legacy(payload: dict):
    """Legacy endpoint — wraps new chat pipeline."""
    request = ChatRequest(
        user_id=payload.get("user_id", "anonymous"),
        session_id=payload.get("session_id"),
        role=payload.get("role", "citizen"),
        message=payload.get("query", payload.get("message", "")),
        language=payload.get("language", "English"),
    )
    try:
        response = await process_message(request)
        return {
            "module": "PDSAIBot",
            "response": response.response,
            "intent": response.intent,
            "suggestions": response.suggestions,
        }
    except Exception as exc:
        log.exception("Legacy query error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Data endpoints (direct microservice proxies) ──────────────────────────────

@app.get("/api/bot/stock")
def get_stock(
    location: str = Query(default="", description="District name"),
    commodity: str = Query(default="", description="Commodity (rice/wheat/sugar)"),
):
    """Fetch stock recommendations from SMART-ALLOT."""
    data = fetch_stock_data(location, commodity)
    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])
    return {"module": "PDSAIBot", **data}


@app.get("/api/bot/anomalies")
def get_anomalies(
    location: str = Query(default=""),
    severity: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Fetch anomaly detection results from the Anomaly service."""
    data = fetch_anomaly_data(location, severity, limit)
    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])
    return {"module": "PDSAIBot", **data}


@app.post("/api/bot/predictions")
def get_predictions(body: dict):
    """
    Fetch demand predictions via SMARTAllot /predict-demand.
    If the DB demand model isn't trained, auto-train it first (from dataset/clean_transactions.csv).
    """
    from chatbot.langchain_agent import (
        fetch_smartallot_model_info,
        train_db_demand_model,
        fetch_db_demand_forecast,
    )

    info = fetch_smartallot_model_info()
    if "error" in info:
        raise HTTPException(status_code=502, detail=info["error"])

    if not info.get("db_demand_model_available"):
        trained = train_db_demand_model()
        if "error" in trained:
            raise HTTPException(status_code=422, detail=trained["error"])

    forecast = fetch_db_demand_forecast(
        district=body.get("district", ""),
        afso=body.get("afso", ""),
        fps_id=body.get("fps_id", ""),
        commodity=body.get("commodity", ""),
        periods=int(body.get("future_periods", body.get("periods", 3)) or 3),
    )
    if "error" in forecast:
        raise HTTPException(status_code=502, detail=forecast["error"])
    return {"module": "PDSAIBot", "model_info": info, **forecast}


@app.post("/api/bot/allocations")
def get_allocations(body: dict):
    """Run LP allocation optimisation via SMART-ALLOT service."""
    from chatbot.langchain_agent import fetch_allocation_plan as _alloc
    data = _alloc(
        district=body.get("district", ""),
        periods=int(body.get("future_periods", 3)),
    )
    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])
    return {"module": "PDSAIBot", **data}


# ── Grievance endpoint ────────────────────────────────────────────────────────

@app.post("/api/bot/grievance", response_model=GrievanceResponse)
def file_grievance(request: GrievanceRequest):
    """
    Register a citizen grievance.
    Creates a ticket and returns a tracking ID.
    """
    ticket_id = f"GRV-{uuid.uuid4().hex[:8].upper()}"
    log.info(
        "Grievance filed: ticket=%s user=%s location=%s category=%s",
        ticket_id, request.user_id, request.location, request.category,
    )
    return GrievanceResponse(
        ticket_id=ticket_id,
        status="open",
        message=(
            f"Your grievance has been registered as **{ticket_id}**. "
            "The call centre team will contact you within 48 hours. "
            f"Issue: {request.description[:120]}"
        ),
        estimated_resolution_hours=48,
    )


# ── Session management ────────────────────────────────────────────────────────

@app.get("/api/bot/sessions/{session_id}/history")
def session_history(session_id: str):
    """Return conversation history for a session."""
    turns = memory.get(session_id)
    return {
        "session_id": session_id,
        "turn_count": len(turns),
        "turns": [
            {
                "role": t.role,
                "content": t.content,
                "intent": t.intent,
                "timestamp": t.ts,
            }
            for t in turns
        ],
    }


@app.delete("/api/bot/sessions/{session_id}")
def clear_session(session_id: str):
    """Clear conversation memory for a session."""
    memory.clear(session_id)
    return {"session_id": session_id, "status": "cleared"}


@app.get("/api/bot/sessions")
def sessions_stats():
    """Return active session count."""
    return {"active_sessions": memory.session_count()}


# ── NLU debug endpoint ────────────────────────────────────────────────────────

@app.post("/api/bot/debug/nlu")
def debug_nlu(body: dict):
    """Parse a message through the NLU engine and return raw result (admin use)."""
    from chatbot.nlu_engine import nlu_engine
    text = body.get("message", "")
    if not text:
        raise HTTPException(status_code=422, detail="message is required")
    result = nlu_engine.parse(text)
    return {
        "input": text,
        "intent": result.intent,
        "confidence": result.confidence,
        "entities": result.entities,
        "source": result.source,
    }


# ── Neural TTS endpoint (edge-tts — Microsoft Neural voices) ─────────────────

_TTS_VOICE: dict[str, str] = {
    "English": "en-IN-NeerjaNeural",   # warm Indian-English female
    "Hindi":   "hi-IN-SwaraNeural",    # natural Hindi female
    "Tamil":   "ta-IN-PallaviNeural",  # native Tamil female
    "Telugu":  "te-IN-ShrutiNeural",   # native Telugu female
    "Kannada": "kn-IN-SapnaNeural",    # native Kannada female
}

# Emoji / pictograph Unicode blocks
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F9FF"   # misc symbols, pictographs, emoticons, transport, flags
    "\U00002702-\U000027B0"    # dingbats
    "\U000024C2-\U0001F251"    # enclosed chars
    "\U0001FA00-\U0001FA6F"    # chess, medical
    "\U0001FA70-\U0001FAFF"    # food, drink, etc.
    "☀-⛿"            # misc symbols (⚠ ✅ etc.)
    "✀-➿"            # dingbats
    "︀-️"            # variation selectors
    "‍"                   # zero-width joiner
    "]+",
    flags=re.UNICODE,
)

_MD_STRIP = re.compile(
    r"#{1,6}\s?|"               # headings
    r"\*{1,2}([^*\n]+)\*{1,2}|"  # bold/italic → keep inner text
    r"`[^`]*`|"                 # inline code
    r"\[([^\]]+)\]\([^)]*\)|"  # links → keep label
    r"^[-*+•·]\s+|"            # bullet points
    r"^\d+\.\s+|"              # numbered list
    r"^>\s?|"                   # blockquotes
    r"\|[^\n]+\||"             # table rows
    r"[_~]",                   # underscores / strikethrough
    re.MULTILINE,
)


def _clean_for_tts(text: str) -> str:
    # 1. Remove emojis
    clean = _EMOJI_RE.sub(" ", text)

    # 2. Strip markdown (keep inner text of bold/italic/links)
    clean = _MD_STRIP.sub(lambda m: (m.group(1) or m.group(2) or ""), clean)

    # 3. Convert numbers with thousand-separators so TTS reads them as words
    #    e.g. "1,23,456" or "1,234,567" → "1234567"
    clean = re.sub(r"(\d),(\d)", r"\1\2", clean)   # run twice for "1,23,456" style
    clean = re.sub(r"(\d),(\d)", r"\1\2", clean)

    # 4. Spell out common abbreviations/symbols that TTS mispronounces
    clean = clean.replace("%",  " percent")
    clean = clean.replace("kg", " kilograms")
    clean = clean.replace("KG", " kilograms")
    clean = clean.replace("MT", " metric tonnes")
    clean = clean.replace("Rs.", "Rupees")
    clean = clean.replace("₹",  "Rupees")
    clean = clean.replace("&",  " and ")
    clean = clean.replace("·",  "")
    clean = clean.replace("•",  "")
    clean = clean.replace("→",  "")
    clean = clean.replace("—",  ", ")
    clean = clean.replace("–",  ", ")

    # 5. Collapse newlines → natural pauses
    clean = re.sub(r"\n{2,}", ". ", clean)
    clean = re.sub(r"\n",     " ",  clean)

    # 6. Collapse extra spaces
    clean = re.sub(r"\s{2,}", " ", clean)

    return clean.strip()


@app.post("/api/bot/tts")
async def text_to_speech(body: dict):
    """
    Convert text → MP3 audio using Microsoft Neural TTS via edge-tts.
    Returns audio/mpeg stream ready to play in the browser.
    """
    try:
        import edge_tts
    except ImportError:
        raise HTTPException(status_code=501, detail="edge-tts not installed — run: pip install edge-tts")

    raw_text = body.get("text", "").strip()
    language = body.get("language", "English")
    if not raw_text:
        raise HTTPException(status_code=422, detail="text is required")

    voice = _TTS_VOICE.get(language, _TTS_VOICE["English"])
    clean = _clean_for_tts(raw_text)

    async def _audio_stream():
        communicate = edge_tts.Communicate(clean, voice, rate="-4%", volume="+0%", pitch="+5Hz")
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    return StreamingResponse(_audio_stream(), media_type="audio/mpeg")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8004,
        reload=True,
        reload_includes=["*.py"],
    )
