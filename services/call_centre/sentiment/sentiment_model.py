"""
ML-enhanced sentiment analysis for PDS call centre.

Primary  : sklearn TF-IDF + LogisticRegression trained on PDS-domain phrases.
Fallback : rule-based keyword scoring (always available).

Output contract
---------------
analyze(text) -> SentimentResult
  .score   : float  in [-1.0, 1.0]
  .label   : "Distressed" | "Negative" | "Neutral" | "Positive"
  .keywords: list[str] — matched signal words
  .method  : "ml" | "rule"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Training corpus ───────────────────────────────────────────────────────────
# Labels: 0=Distressed  1=Negative  2=Neutral  3=Positive

_CORPUS: list[tuple[str, int]] = [
    # Distressed (0)
    ("my ration is not available for three weeks this is a disaster", 0),
    ("angry furious they are stealing from us fraud happening at fps shop", 0),
    ("terrible service disgusting behaviour I will escalate to collector", 0),
    ("completely unacceptable my children are starving no food received", 0),
    ("worst experience ever shop owner asked for bribe threatening us", 0),
    ("urgent help needed ration card blocked family has no food supply", 0),
    ("cheating fraud rice not given quantity is short every month", 0),
    ("I am very upset shop is closed three days in a row my complaint", 0),
    ("this is corruption we are suffering please help immediately", 0),
    ("no stock for two months district office not responding at all", 0),

    # Negative (1)
    ("rice not available this month stock problem at fps shop", 1),
    ("complaint about supply delay wheat not received yet", 1),
    ("issue with ration card entitlement not updated problem", 1),
    ("fps shop was closed when I went to collect my ration", 1),
    ("delay in distribution supply has not reached our area", 1),
    ("short supply given less than entitlement quantity", 1),
    ("ration card not linked to shop issue with record", 1),
    ("I need to register a grievance about missing stock", 1),
    ("supply late by two weeks not acceptable problem reported", 1),
    ("incorrect quantity dispensed want to file complaint", 1),

    # Neutral (2)
    ("when will the stock arrive at our fps shop", 2),
    ("I want to check my entitlement and allocation", 2),
    ("what is the process to update ration card details", 2),
    ("please tell me the distribution schedule for this month", 2),
    ("I want to know the status of my ticket number tkt 001", 2),
    ("checking stock availability in guntur district please", 2),
    ("what documents do I need to apply for ration card", 2),
    ("how do I contact the district supply officer", 2),
    ("information about beneficiary registration process", 2),
    ("I need details about commodity allocation wheat rice", 2),
    ("general inquiry about pds services and benefits", 2),
    ("transfer my ration card to new address how to do", 2),

    # Positive (3)
    ("thank you the issue has been resolved very helpful service", 3),
    ("received my ration on time this month very satisfied", 3),
    ("excellent service agent was very helpful and polite", 3),
    ("ticket resolved quickly impressed with the response time", 3),
    ("good service problem fixed quickly thank you very much", 3),
    ("ration card updated successfully good experience", 3),
    ("very helpful staff resolved my complaint efficiently", 3),
    ("stock available at shop received full entitlement happy", 3),
    ("satisfied with the support thank you for your help", 3),
    ("issue sorted out within hours great support team", 3),
]

# ── Keyword rule engine ───────────────────────────────────────────────────────

_SIGNALS: dict[str, tuple[float, list[str]]] = {
    "distressed": (-0.90, ["furious", "starving", "disaster", "disgusting", "corruption",
                            "stealing", "bribe", "threatening", "worst ever", "unacceptable"]),
    "very_negative": (-0.60, ["urgent", "fraud", "complaint", "not available", "blocked",
                               "cheating", "no food", "not received", "terrible"]),
    "negative": (-0.30, ["delay", "late", "issue", "problem", "closed", "short supply",
                          "grievance", "unavailable", "ration not given", "not linked"]),
    "neutral": (0.00, ["check", "status", "when", "process", "how to", "information",
                        "schedule", "inquiry", "details", "update", "register", "apply"]),
    "positive": (0.40, ["thank", "resolved", "satisfied", "helpful", "received", "good",
                         "excellent", "happy", "great", "impressed", "quickly"]),
    "very_positive": (0.80, ["outstanding", "perfect", "best", "very satisfied",
                               "fully resolved", "amazing"]),
}

_SCORE_TO_LABEL = [(-0.55, "Distressed"), (-0.25, "Negative"), (0.20, "Neutral"), (1.01, "Positive")]


def _rule_score(text: str) -> tuple[float, list[str]]:
    lower = text.lower()
    score = 0.0
    hits: list[str] = []
    for bucket, (delta, words) in _SIGNALS.items():
        for w in words:
            if w in lower:
                hits.append(w)
                score += delta * 0.4   # weighted accumulation
    return max(-1.0, min(1.0, round(score, 3))), hits


# ── ML classifier ─────────────────────────────────────────────────────────────

@dataclass
class SentimentResult:
    score: float
    label: str
    keywords: list[str] = field(default_factory=list)
    method: str = "rule"


# Score boundaries for four classes → [-1,1] map
_CLASS_CENTERS = {0: -0.85, 1: -0.40, 2: 0.05, 3: 0.70}


class SentimentAnalyzer:
    """Hybrid ML + rule-based sentiment analyzer trained on PDS domain text."""

    def __init__(self) -> None:
        self._pipeline = None
        self._ready = False
        self._train()

    def _train(self) -> None:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline

            texts  = [t for t, _ in _CORPUS]
            labels = [l for _, l in _CORPUS]

            self._pipeline = Pipeline([
                ("tfidf", TfidfVectorizer(ngram_range=(1, 3), min_df=1, sublinear_tf=True)),
                ("clf",   LogisticRegression(max_iter=500, C=2.0, class_weight="balanced")),
            ])
            self._pipeline.fit(texts, labels)
            self._ready = True
        except ImportError:
            pass

    def analyze(self, text: str) -> SentimentResult:
        rule_score, kw = _rule_score(text)

        if self._ready and self._pipeline is not None:
            try:
                cls  = int(self._pipeline.predict([text])[0])
                proba = self._pipeline.predict_proba([text])[0]
                confidence = float(proba[cls])

                # Blend ML class center with rule score (weighted by ML confidence)
                ml_score   = _CLASS_CENTERS[cls]
                blend      = ml_score * confidence + rule_score * (1 - confidence)
                score      = round(max(-1.0, min(1.0, blend)), 3)
                method     = "ml"
            except Exception:
                score, method = rule_score, "rule"
        else:
            score, method = rule_score, "rule"

        # Label from score
        label = "Positive"
        for threshold, lbl in _SCORE_TO_LABEL:
            if score < threshold:
                label = lbl
                break

        return SentimentResult(score=score, label=label, keywords=kw[:6], method=method)

    def analyze_legacy(self, text: str) -> tuple[float, str]:
        """Drop-in replacement for ai_service.analyze_sentiment()."""
        r = self.analyze(text)
        return r.score, r.label


# Module singleton — trained once on import
sentiment_analyzer = SentimentAnalyzer()
