"""AI service — Claude API with rule-based fallback."""
from __future__ import annotations

from shared.config import settings

_SYSTEM_TEMPLATE = """You are an AI voice agent for Andhra Pradesh's Public Distribution System (PDS) call centre.
Caller type: {caller_type}. Language: {language}.

Your job:
- Answer queries about ration cards, rice/wheat/sugar stock, FPS (fair price shop) operations
- Register complaints and provide ticket numbers when needed
- Be concise (under 80 words), warm, and voice-friendly — no markdown, no lists, no symbols
- Respond ONLY in {language}

Domain context:
- PDS distributes subsidised rice, wheat, sugar, and kerosene to beneficiaries
- FPS shops open based on government schedule; stocks arrive from district warehouses
- Common issues: stock unavailability, entitlement errors, supply delays, card problems

If the issue requires human follow-up, say so and mention a ticket will be created."""

FALLBACK_RESPONSES: dict[str, dict[str, str]] = {
    "English": {
        "stock_availability": "I understand your concern about stock availability. Our records show the district supply team is managing the distribution. I'll create a ticket for immediate attention and you'll receive an update within 4 hours.",
        "entitlement": "For entitlement or ration card issues, you'll need to verify your details with the Citizens Records Team. I'm raising a priority ticket for you right now.",
        "supply_delay": "I'm sorry to hear about the supply delay. I've noted this and will escalate to the Logistics Control Room. A support ticket has been created.",
        "general": "Thank you for reaching out to PDS360 Call Centre. I've registered your concern and a support agent will follow up with you shortly.",
    },
    "Telugu": {
        "stock_availability": "మీ స్టాక్ సమస్య అర్థమైంది. జిల్లా సరఫరా బృందం వెంటనే దీన్ని పరిష్కరిస్తుంది. 4 గంటల్లో అప్‌డేట్ వస్తుంది.",
        "entitlement": "రేషన్ కార్డు సమస్య కోసం పౌర రికార్డుల బృందానికి టికెట్ పంపాను. మీకు త్వరలో సమాచారం వస్తుంది.",
        "supply_delay": "సరఫరా ఆలస్యానికి క్షమాపణలు. లాజిస్టిక్స్ నియంత్రణ గదికి ఈ విషయాన్ని ఎస్కలేట్ చేశాను.",
        "general": "PDS360 కాల్ సెంటర్‌కు సంప్రదించినందుకు ధన్యవాదాలు. మీ సమస్య నమోదు చేయబడింది.",
    },
    "Hindi": {
        "stock_availability": "స్టాక్ की समस्या समझ आई। जिला आपूर्ति टीम इसे तुरंत देखेगी। 4 घंटे में अपडेट मिलेगा।",
        "entitlement": "राशन कार्ड की समस्या के लिए नागरिक रिकॉर्ड टीम को टिकट भेज दिया है। जल्द ही संपर्क किया जाएगा।",
        "supply_delay": "आपूर्ति में देरी के लिए खेद है। लॉजिस्टिक्स कंट्रोल रूम को सूचित कर दिया है।",
        "general": "PDS360 कॉल सेंटर से संपर्क करने के लिए धन्यवाद। आपकी समस्या दर्ज हो गई है।",
    },
}

CATEGORY_KEYWORDS = {
    "stock_availability": ["stock", "not available", "unavailable", "rice", "wheat", "sugar", "ration"],
    "entitlement": ["card", "entitlement", "ration card", "beneficiary"],
    "supply_delay": ["delay", "late", "dispatch", "transit"],
}


def _detect_category(text: str) -> str:
    lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return category
    return "general"


def _fallback_response(text: str, language: str) -> str:
    category = _detect_category(text)
    lang_responses = FALLBACK_RESPONSES.get(language, FALLBACK_RESPONSES["English"])
    return lang_responses.get(category, lang_responses["general"])


def generate_response(query: str, language: str, caller_type: str) -> str:
    if not settings.anthropic_api_key:
        return _fallback_response(query, language)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        system = _SYSTEM_TEMPLATE.format(caller_type=caller_type, language=language)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": query}],
        )
        return message.content[0].text.strip()
    except Exception:
        return _fallback_response(query, language)


def analyze_sentiment(text: str) -> tuple[float, str]:
    lower = text.lower()
    score = 0.0
    negative = ["delay", "late", "not available", "complaint", "issue", "urgent", "frustrated", "problem"]
    positive = ["thank", "resolved", "good", "satisfied", "helpful"]
    distressed = ["angry", "furious", "terrible", "worst", "disgusting"]
    for w in distressed:
        if w in lower:
            score -= 0.35
    for w in negative:
        if w in lower:
            score -= 0.18
    for w in positive:
        if w in lower:
            score += 0.12
    score = max(-1.0, min(1.0, round(score, 2)))
    if score <= -0.55:
        label = "Distressed"
    elif score <= -0.25:
        label = "Negative"
    elif score < 0.2:
        label = "Neutral"
    else:
        label = "Positive"
    return score, label


def needs_ticket(query: str, ai_response: str) -> bool:
    signals = ["complaint", "register", "not available", "issue", "problem", "delay", "grievance", "urgent", "ticket"]
    lower = query.lower()
    return any(s in lower for s in signals) or "ticket" in ai_response.lower()
