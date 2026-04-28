"""
Rasa-inspired NLU engine with multilingual support.

Primary path  → Rasa HTTP server (if RASA_URL env var is set and server is alive).
Fallback path → embedded sklearn TF-IDF + cosine similarity, trained on rasa/nlu.yml.
Both paths return the same NLUResult structure.

Multilingual: keywords cover English, Telugu, Hindi, Tamil, and Kannada for all
major intents and entities so NLU works even before translation kicks in.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

_NLU_YAML = Path(__file__).resolve().parents[1] / "rasa" / "nlu.yml"


# ── Known entity values (English + major South Indian languages) ──────────────

KNOWN_LOCATIONS = [
    # English
    "guntur", "krishna", "nandyal", "kurnool", "palnadu",
    "tirupati", "vijayawada", "visakhapatnam", "kadapa", "anantapur",
    "annamayya", "chittoor", "srikakulam", "west godavari", "east godavari",
    "prakasam", "spsr nellore", "nellore", "eluru", "bapatla",
]

# English canonical → normalised label used in ML model
_COMMODITY_CANONICAL: dict[str, str] = {
    # English
    "rice":          "Fine Rice",
    "fine rice":     "Fine Rice",
    "fortified rice":"Fine Rice",
    "wheat":         "Atta",
    "atta":          "Atta",
    "flour":         "Atta",
    "sugar":         "Sugar",
    "dal":           "Dal",
    "lentil":        "Dal",
    "pulses":        "Dal",
    "jowar":         "Jowar",
    "sorghum":       "Jowar",
    "raagi":         "Raagi",
    "ragi":          "Raagi",
    "millet":        "Raagi",
    "kerosene":      "Kerosene",
    "oil":           "Oil",
    # Telugu
    "బియ్యం":         "Fine Rice",
    "అన్నం":          "Fine Rice",
    "గోధుమలు":        "Atta",
    "ఆటా":           "Atta",
    "చక్కెర":         "Sugar",
    "పప్పు":          "Dal",
    "జొన్నలు":        "Jowar",
    "రాగి":           "Raagi",
    "కిరోసిన్":       "Kerosene",
    # Hindi
    "चावल":          "Fine Rice",
    "गेहूं":          "Atta",
    "गेहु":           "Atta",
    "आटा":           "Atta",
    "चीनी":          "Sugar",
    "शक्कर":         "Sugar",
    "दाल":           "Dal",
    "ज्वार":         "Jowar",
    "रागी":          "Raagi",
    "मिट्टी का तेल": "Kerosene",
    # Tamil
    "அரிசி":         "Fine Rice",
    "கோதுமை":        "Atta",
    "சர்க்கரை":       "Sugar",
    "பருப்பு":        "Dal",
    "சோளம்":         "Jowar",
    "ராகி":          "Raagi",
    # Kannada
    "ಅಕ್ಕಿ":          "Fine Rice",
    "ಗೋಧಿ":          "Atta",
    "ಸಕ್ಕರೆ":         "Sugar",
    "ಬೇಳೆ":          "Dal",
    "ಜೋಳ":          "Jowar",
    "ರಾಗಿ":          "Raagi",
}

KNOWN_COMMODITIES = list(_COMMODITY_CANONICAL.keys())

_TX_RE  = re.compile(r"\b(TXN[-\s]?\d+|\d{4,})\b", re.IGNORECASE)
_NUM_RE = re.compile(r"\b(\d+)\s*months?\b", re.IGNORECASE)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class EntityHit:
    entity: str
    value:  str
    start:  int = 0
    end:    int = 0


@dataclass
class NLUResult:
    intent:     str
    confidence: float
    entities:   dict[str, Any] = field(default_factory=dict)
    source:     str = "embedded"   # "embedded" | "rasa_server"


# ── Entity extractor ──────────────────────────────────────────────────────────

def extract_entities(text: str) -> dict[str, Any]:
    lower = text.lower()
    entities: dict[str, Any] = {}

    # Location (English normalised)
    for loc in KNOWN_LOCATIONS:
        if loc in lower:
            entities["location"] = loc.title()
            break

    # Commodity — longest match first to prefer "Fine Rice" over "rice"
    for token in sorted(KNOWN_COMMODITIES, key=len, reverse=True):
        if token.lower() in lower or token in text:
            entities["commodity"] = _COMMODITY_CANONICAL.get(token.lower(), token)
            break

    # Transaction ID
    m = _TX_RE.search(text)
    if m:
        entities["transaction_id"] = m.group(0).upper().replace(" ", "-")

    # Future periods
    m = _NUM_RE.search(lower)
    if m:
        entities["future_periods"] = int(m.group(1))

    return entities


# ── Embedded sklearn engine ───────────────────────────────────────────────────

class EmbeddedNLU:
    """TF-IDF + cosine similarity trained directly from rasa/nlu.yml."""

    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 3), min_df=1, analyzer="word", sublinear_tf=True)
        self._labels: list[str] = []
        self._X = None
        self._ready = False
        self._load()

    def _load(self) -> None:
        try:
            import yaml
        except ImportError:
            log.warning("PyYAML not installed — NLU engine will use keyword fallback")
            return
        if not _NLU_YAML.exists():
            log.warning("rasa/nlu.yml not found — NLU engine will use keyword fallback")
            return

        data = yaml.safe_load(_NLU_YAML.read_text(encoding="utf-8"))
        nlu_items = data.get("nlu", [])
        examples, labels = [], []
        for item in nlu_items:
            if not isinstance(item, dict) or "intent" not in item:
                continue
            intent_name = item["intent"]
            raw = item.get("examples", "")
            for line in raw.strip().split("\n"):
                line = line.strip().lstrip("- ").strip()
                line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
                if line:
                    examples.append(line)
                    labels.append(intent_name)

        if not examples:
            return

        self._X = self._vectorizer.fit_transform(examples)
        self._labels = labels
        self._ready = True
        log.info("Embedded NLU loaded %d training examples across %d intents",
                 len(examples), len(set(labels)))

    def parse(self, text: str) -> NLUResult:
        if not self._ready:
            return self._keyword_fallback(text)

        vec = self._vectorizer.transform([text])
        sims = np.asarray(self._X.dot(vec.T).todense()).flatten()

        intent_scores: dict[str, float] = {}
        for idx, label in enumerate(self._labels):
            score = float(sims[idx])
            if score > intent_scores.get(label, -1.0):
                intent_scores[label] = score

        best_intent = max(intent_scores, key=lambda k: intent_scores[k])
        confidence  = intent_scores[best_intent]

        # If TF-IDF confidence is low, fall back to keyword matching which handles
        # multilingual input better
        if confidence < 0.25:
            kw = self._keyword_fallback(text)
            if kw.confidence >= 0.50:
                return kw

        return NLUResult(
            intent=best_intent,
            confidence=round(confidence, 4),
            entities=extract_entities(text),
            source="embedded",
        )

    def _keyword_fallback(self, text: str) -> NLUResult:
        """
        Keyword-based fallback covering English + Telugu + Hindi + Tamil + Kannada.
        Checks longer / more specific patterns first to avoid false positives.
        """
        lower = text.lower()

        kw_map: list[tuple[list[str], str]] = [
            # ── Fraud / complaint ──────────────────────────────────────────────
            (["fraud", "corrupt", "brib", "divert", "black market", "ghost beneficiary",
              "illegal", "stolen ration", "నకిలీ", "भ्रष्ट", "மோசடி", "ಭ್ರಷ್ಟ"],
             "complaint_fraud"),

            # ── Entitlement / quota ────────────────────────────────────────────
            (["entitlement", "entitled", "quota", "eligible", "how much do i get",
              "monthly ration", "ration card", "how many kg", "నా హక్కు", "నా వాటా",
              "मेरा हिस्सा", "मेरा राशन", "எனது உரிமை", "ನನ್ನ ಪಾಲು"],
             "entitlement_query"),

            # ── Beneficiary / card lookup ──────────────────────────────────────
            (["beneficiary", "card number", "card holder", "fps card", "ration card number",
              "find card", "card details", "లబ్ధిదారు", "कार्ड धारक", "பயனாளி"],
             "beneficiary_lookup"),

            # ── Distribution schedule ──────────────────────────────────────────
            (["distribution", "schedule", "when is", "next distribution", "ration date",
              "delivery date", "shop open", "పంపిణీ తేదీ", "वितरण कब", "விநியோக தேதி",
              "ವಿತರಣೆ ದಿನ"],
             "distribution_schedule"),

            # ── FPS location ───────────────────────────────────────────────────
            (["where is my fps", "fps location", "ration shop address", "nearest fps",
              "fair price shop", "నా రేషన్ షాప్", "मेरी राशन दुकान", "என் ரேஷன் கடை"],
             "fps_location"),

            # ── Stock / inventory ──────────────────────────────────────────────
            (["stock", "inventory", "available", "how much", "check stock", "stoc",
              "నిల్వ", "స్టాక్", "भंडार", "स्टॉक", "சரக்கு", "ಸ್ಟಾಕ್"],
             "stock_check"),

            # ── Anomaly / alerts ───────────────────────────────────────────────
            (["anomal", "alert", "delay", "irregular", "flag", "suspicious", "mismatch",
              "అసంగతత", "विसंगति", "முரண்பாடு", "ಅಸಂಗತಿ"],
             "anomaly_check"),

            # ── Demand / forecast ──────────────────────────────────────────────
            (["predict", "forecast", "demand", "future", "next month", "upcoming",
              "projection", "అంచనా", "ముందుగా", "भविष्य", "पूर्वानुमान",
              "முன்கணிப்பு", "ಮುನ್ಸೂಚನೆ"],
             "demand_prediction"),

            # ── Allocation / recommendation ────────────────────────────────────
            (["allocat", "recommend", "optimal", "distribute", "allotment", "optimize",
              "కేటాయింపు", "आवंटन", "ஒதுக்கீடு", "ಹಂಚಿಕೆ"],
             "allocation_recommendation"),

            # ── Compliance / performance ───────────────────────────────────────
            (["compliance", "compliant", "performance", "kpi", "indicator", "audit",
              "regulation", "నిబంధన", "अनुपालन", "இணக்கம்", "ಅನುಸರಣೆ"],
             "compliance_check"),

            # ── Delivery / tracking ────────────────────────────────────────────
            (["delivery", "shipment", "track", "status", "where is", "txn", "transit",
              "డెలివరీ", "配达", "डिलीवरी", "விநியோகம்", "ವಿತರಣೆ"],
             "delivery_status"),

            # ── Grievance / complaint ──────────────────────────────────────────
            (["complaint", "grievance", "report", "issue", "problem", "ration not",
              "complaint", "file complaint", "ఫిర్యాదు", "సమస్య", "शिकायत",
              "புகார்", "ದೂರು"],
             "grievance"),

            # ── Greetings ──────────────────────────────────────────────────────
            (["hello", "hi", "hey", "good morning", "good afternoon", "good evening",
              "namaste", "vanakkam", "నమస్కారం", "నమస్తే", "नमस्ते", "வணக்கம்", "ನಮಸ್ಕಾರ"],
             "greeting"),

            # ── Farewell ───────────────────────────────────────────────────────
            (["bye", "goodbye", "exit", "thank you", "thanks", "ok thanks",
              "ధన్యవాదాలు", "धन्यवाद", "நன்றி", "ಧನ್ಯವಾದ"],
             "farewell"),

            # ── Help ───────────────────────────────────────────────────────────
            (["help", "what can you", "guide", "assist", "capabilities", "what do you do",
              "సహాయం", "मदद", "உதவி", "ಸಹಾಯ"],
             "help"),
        ]

        for keywords, intent in kw_map:
            if any(kw in lower or kw in text for kw in keywords):
                return NLUResult(
                    intent=intent,
                    confidence=0.60,
                    entities=extract_entities(text),
                    source="embedded_kw",
                )

        return NLUResult(intent="general_query", confidence=0.30, entities=extract_entities(text), source="embedded_kw")


# ── Rasa HTTP proxy ───────────────────────────────────────────────────────────

class RasaServerNLU:
    """Thin proxy to a real Rasa NLU server at RASA_URL/model/parse."""

    def __init__(self, base_url: str) -> None:
        self._url = base_url.rstrip("/") + "/model/parse"

    def parse(self, text: str) -> NLUResult | None:
        try:
            import httpx
            resp = httpx.post(self._url, json={"text": text}, timeout=3.0)
            if resp.status_code != 200:
                return None
            d = resp.json()
            intent = d.get("intent", {})
            raw_entities = d.get("entities", [])
            merged = extract_entities(text)
            for e in raw_entities:
                merged[e["entity"]] = e["value"]
            return NLUResult(
                intent=intent.get("name", "general_query"),
                confidence=round(float(intent.get("confidence", 0.5)), 4),
                entities=merged,
                source="rasa_server",
            )
        except Exception as exc:
            log.debug("Rasa server unavailable: %s", exc)
            return None


# ── Unified facade ────────────────────────────────────────────────────────────

class NLUEngine:
    """
    Tries Rasa server first, falls back to embedded sklearn NLU.
    Hot-path: embedded is always available; Rasa server is optional.
    """

    def __init__(self) -> None:
        self._embedded = EmbeddedNLU()
        rasa_url = os.getenv("RASA_URL", "").strip()
        self._rasa = RasaServerNLU(rasa_url) if rasa_url else None

    def parse(self, text: str) -> NLUResult:
        if self._rasa:
            result = self._rasa.parse(text)
            if result:
                log.debug("NLU via Rasa server: intent=%s conf=%.3f", result.intent, result.confidence)
                return result
        result = self._embedded.parse(text)
        log.debug("NLU via embedded: intent=%s conf=%.3f", result.intent, result.confidence)
        return result


# Singleton
nlu_engine = NLUEngine()
