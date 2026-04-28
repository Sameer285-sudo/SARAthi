"""
Central orchestrator for PDSAI-Bot.

Pipeline:
  1. Language detection  → detect script/language of input message
  2. Translation in      → translate non-English input to English for NLU
  3. NLU Engine          → intent + confidence + entities
  4. RBAC check          → deny if role lacks access
  5. Slot carry-over     → merge prior-turn entities
  6. Agent selection     → LangChain (complex) or structured (simple)
  7. Translation out     → translate response back to user's language
  8. Memory update       → store turn for future context
  9. Response builder    → structured ChatResponse
"""
from __future__ import annotations

import logging
import uuid

from models.schemas import ChatRequest, ChatResponse
from chatbot.memory import memory
from chatbot.nlu_engine import nlu_engine
from chatbot.langchain_agent import langchain_agent
from chatbot.response_builder import build_response
from chatbot.translator import detect, lang_name_to_code, to_english, from_english, LANG_NAMES
from utils.rbac import can_access, should_use_langchain, denied_response

log = logging.getLogger(__name__)

# Intents handled with canned responses (no microservice call needed)
_CANNED_INTENTS = {"greeting", "farewell", "help"}

_CANNED: dict[str, str] = {
    "greeting": (
        "Hello! I'm SARATHI, your AI assistant for Andhra Pradesh's Public Distribution System.\n\n"
        "I can help you with:\n"
        "• Stock levels and allotment data\n"
        "• Demand forecasts (GradientBoosting ML, May 2026)\n"
        "• Anomaly detection and fraud alerts\n"
        "• Ration entitlements and FPS location\n"
        "• Delivery tracking\n"
        "• Grievance and complaint support\n\n"
        "You can ask me in **English, Telugu, Hindi, Tamil, or Kannada**!\n\n"
        "What would you like to know?"
    ),
    "farewell": (
        "Goodbye! If you need more help with PDS operations, feel free to return.\n"
        "For urgent issues, call the PDS Helpline: **1967** (toll-free, 24×7). Have a great day!"
    ),
    "help": (
        "**SARATHI — What I Can Do**\n\n"
        "**For Administrators**\n"
        "  • *Show stock levels in Annamayya* → allotment and forecast data\n"
        "  • *Predict demand for rice next 3 months* → GradientBoosting ML forecast\n"
        "  • *Show anomalies in Chittoor* → flagged transactions with severity\n"
        "  • *Compliance report for Annamayya* → KPI benchmarks\n\n"
        "**For Field Staff**\n"
        "  • *Stock status for Fine Rice* → current allotment recommendations\n"
        "  • *Delivery status for TXN-1042* → tracking and delay info\n"
        "  • *Any anomalies today?* → real-time alert summary\n\n"
        "**For Citizens**\n"
        "  • *What is my monthly rice quota?* → entitlement details\n"
        "  • *Where is my FPS shop?* → locator guide\n"
        "  • *I want to file a complaint* → grievance support\n"
        "  • *When is next distribution?* → schedule info\n\n"
        "**Languages:** English | Telugu | Hindi | Tamil | Kannada\n\n"
        "Try any of the above, or ask freely!"
    ),
}


async def process_message(request: ChatRequest) -> ChatResponse:
    """Full pipeline: language detect → NLU → RBAC → agent → translate → response."""
    session_id = request.session_id or str(uuid.uuid4())

    # ── 1. Resolve user language ───────────────────────────────────────────────
    # If client sent an explicit non-English language, honour it.
    # Otherwise detect from the message text.
    explicit_code = lang_name_to_code(request.language)
    if explicit_code != "en":
        lang_code = explicit_code
    else:
        lang_code = detect(request.message)

    lang_display = LANG_NAMES.get(lang_code, request.language)

    # ── 2. Translate input → English for NLU processing ───────────────────────
    if lang_code != "en":
        msg_for_nlu = to_english(request.message, src=lang_code)
        log.info("Translated [%s→en]: %r → %r", lang_code, request.message[:60], msg_for_nlu[:60])
    else:
        msg_for_nlu = request.message

    # ── 3. NLU ────────────────────────────────────────────────────────────────
    nlu = nlu_engine.parse(msg_for_nlu)
    # Also run entity extraction on original text (catches native-language commodity names)
    if lang_code != "en":
        from chatbot.nlu_engine import extract_entities
        native_entities = extract_entities(request.message)
        for k, v in native_entities.items():
            if k not in nlu.entities:
                nlu.entities[k] = v

    intent     = nlu.intent
    confidence = nlu.confidence
    entities   = dict(nlu.entities)

    log.info(
        "session=%s role=%s lang=%s intent=%s conf=%.3f entities=%s src=%s",
        session_id, request.role, lang_code, intent, confidence, entities, nlu.source,
    )

    # ── 4. RBAC ───────────────────────────────────────────────────────────────
    if not can_access(request.role, intent):
        log.warning("Access denied: role=%s intent=%s", request.role, intent)
        denied = denied_response(request.role, intent)
        denied_out = from_english(denied, target=lang_code) if lang_code != "en" else denied
        return build_response(
            session_id=session_id,
            user_id=request.user_id,
            role=request.role,
            message=request.message,
            nlu_intent=intent,
            nlu_confidence=confidence,
            nlu_source=nlu.source,
            response_text=denied_out,
            agent_source="rbac",
            data={"denied": True, "intent": intent, "role": request.role},
            language=lang_display,
        )

    # ── 5. Canned responses ────────────────────────────────────────────────────
    if intent in _CANNED_INTENTS:
        canned = _CANNED[intent]
        canned_out = from_english(canned, target=lang_code) if lang_code != "en" else canned
        memory.add(session_id, "user", request.message, intent)
        memory.add(session_id, "assistant", canned_out)
        return build_response(
            session_id=session_id,
            user_id=request.user_id,
            role=request.role,
            message=request.message,
            nlu_intent=intent,
            nlu_confidence=confidence,
            nlu_source=nlu.source,
            response_text=canned_out,
            agent_source="canned",
            data={},
            language=lang_display,
        )

    # ── 6. Slot carry-over ────────────────────────────────────────────────────
    prior_entities = memory.get_last_entities(session_id)
    for key, val in prior_entities.items():
        if key not in entities:
            entities[key] = val
            log.debug("Slot carry-over: %s=%s", key, val)

    # ── 7. Conversation context for LangChain ─────────────────────────────────
    context = memory.get_context_string(session_id, last_n=4)

    # ── 8. Agent selection ────────────────────────────────────────────────────
    use_lc = should_use_langchain(request.role, intent, confidence)
    if use_lc:
        # Pass original message to LangChain so Claude can respond in user's language natively
        agent_msg = request.message if langchain_agent.is_llm_ready else msg_for_nlu
        log.debug("Routing to LangChain (intent=%s conf=%.3f llm_ready=%s)",
                  intent, confidence, langchain_agent.is_llm_ready)
        response_text, data = langchain_agent.run(
            message=agent_msg,
            role=request.role,
            intent=intent,
            entities=entities,
            context=context,
        )
        agent_source = "langchain" if langchain_agent.is_llm_ready else "structured_fallback"
    else:
        log.debug("Routing to structured handler (intent=%s conf=%.3f)", intent, confidence)
        response_text, data = langchain_agent._run_structured(intent, entities, request.role)
        agent_source = "structured"

    # ── 9. Translate response back to user language ───────────────────────────
    # LangChain (Claude) handles multilingual natively; only translate structured responses
    if lang_code != "en" and agent_source in ("structured", "structured_fallback", "canned"):
        response_text = from_english(response_text, target=lang_code)

    # ── 10. Memory update ──────────────────────────────────────────────────────
    memory.add(session_id, "user", request.message, intent)
    memory.add(session_id, "assistant", response_text)

    # ── 11. Build response ─────────────────────────────────────────────────────
    return build_response(
        session_id=session_id,
        user_id=request.user_id,
        role=request.role,
        message=request.message,
        nlu_intent=intent,
        nlu_confidence=confidence,
        nlu_source=nlu.source,
        response_text=response_text,
        agent_source=agent_source,
        data=data,
        language=lang_display,
    )
