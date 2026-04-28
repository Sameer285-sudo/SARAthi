"""
Simple in-memory TTL cache for visualization endpoints.
Avoids re-running expensive aggregation queries on every request.
"""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    def __init__(self, default_ttl: float = 30.0) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        self._store[key] = (value, time.monotonic() + (ttl or self.default_ttl))

    def invalidate(self, prefix: str = "") -> None:
        if not prefix:
            self._store.clear()
            return
        to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in to_delete:
            del self._store[k]

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


# Module-level singleton — import this everywhere
chart_cache = TTLCache(default_ttl=30.0)   # 30-second TTL for chart data
alert_cache  = TTLCache(default_ttl=10.0)  # 10-second TTL for alerts
