from __future__ import annotations

from threading import RLock
from time import monotonic
from typing import Generic, Hashable, TypeVar


T = TypeVar("T")


class TtlCache(Generic[T]):
    def __init__(self, ttl_seconds: float, max_size: int = 128) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._items: dict[Hashable, tuple[float, T]] = {}
        self._lock = RLock()

    def get(self, key: Hashable) -> T | None:
        now = monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._items.pop(key, None)
                return None
            return value

    def set(self, key: Hashable, value: T) -> T:
        with self._lock:
            if len(self._items) >= self.max_size:
                oldest_key = min(self._items, key=lambda item_key: self._items[item_key][0])
                self._items.pop(oldest_key, None)
            self._items[key] = (monotonic() + self.ttl_seconds, value)
        return value
