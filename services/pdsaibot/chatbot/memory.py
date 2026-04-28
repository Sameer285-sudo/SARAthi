"""
In-memory conversation history per session.
Stores the last N turns for multi-turn context.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Turn:
    role: str        # "user" | "assistant"
    content: str
    intent: str = ""
    ts: float = field(default_factory=time.time)


class ConversationMemory:
    def __init__(self, max_turns: int = 10, session_ttl: float = 3600.0) -> None:
        self._history: dict[str, list[Turn]] = defaultdict(list)
        self._last_access: dict[str, float] = {}
        self._max_turns = max_turns
        self._session_ttl = session_ttl

    def add(self, session_id: str, role: str, content: str, intent: str = "") -> None:
        self._history[session_id].append(Turn(role=role, content=content, intent=intent))
        self._last_access[session_id] = time.time()
        # Keep only last N turns
        if len(self._history[session_id]) > self._max_turns * 2:
            self._history[session_id] = self._history[session_id][-self._max_turns * 2:]

    def get(self, session_id: str) -> list[Turn]:
        self._evict_stale()
        return list(self._history.get(session_id, []))

    def get_context_string(self, session_id: str, last_n: int = 4) -> str:
        turns = self.get(session_id)[-last_n * 2:]
        lines = []
        for t in turns:
            prefix = "User" if t.role == "user" else "Assistant"
            lines.append(f"{prefix}: {t.content}")
        return "\n".join(lines)

    def get_last_intent(self, session_id: str) -> str:
        turns = [t for t in self.get(session_id) if t.role == "user" and t.intent]
        return turns[-1].intent if turns else ""

    def get_last_entities(self, session_id: str) -> dict[str, str]:
        """Return extracted entities from recent turns for slot carry-over."""
        entities: dict[str, str] = {}
        for turn in self.get(session_id)[-6:]:
            if hasattr(turn, "_entities"):
                entities.update(turn._entities)  # type: ignore[attr-defined]
        return entities

    def clear(self, session_id: str) -> None:
        self._history.pop(session_id, None)
        self._last_access.pop(session_id, None)

    def _evict_stale(self) -> None:
        now = time.time()
        stale = [sid for sid, last in self._last_access.items() if now - last > self._session_ttl]
        for sid in stale:
            self._history.pop(sid, None)
            self._last_access.pop(sid, None)

    def session_count(self) -> int:
        return len(self._history)


# Module-level singleton
memory = ConversationMemory(max_turns=12, session_ttl=3600.0)
