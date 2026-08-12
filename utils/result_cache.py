from collections import OrderedDict
from threading import RLock
from typing import Optional


class ResultCache:
    """Thread-safe in-memory LRU cache with item and total-byte limits."""

    def __init__(
        self,
        max_items: int = 64,
        max_bytes: int = 256 * 1024 * 1024,
        max_item_bytes: int = 48 * 1024 * 1024,
    ):
        if max_items <= 0 or max_bytes <= 0 or max_item_bytes <= 0:
            raise ValueError("Cache limits must be positive.")
        self._lock = RLock()
        self._store: OrderedDict[str, bytes] = OrderedDict()
        self._max_items = int(max_items)
        self._max_bytes = int(max_bytes)
        self._max_item_bytes = int(max_item_bytes)
        self._total_bytes = 0

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            value = self._store.get(key)
            if value is not None:
                self._store.move_to_end(key)
            return value

    def set(self, key: str, value: bytes) -> None:
        if not isinstance(value, bytes):
            raise TypeError("Cached result must be bytes.")
        if len(value) > self._max_item_bytes:
            return
        with self._lock:
            previous = self._store.pop(key, None)
            if previous is not None:
                self._total_bytes -= len(previous)
            self._store[key] = value
            self._total_bytes += len(value)
            self._store.move_to_end(key)
            while self._store and (
                len(self._store) > self._max_items or self._total_bytes > self._max_bytes
            ):
                _, removed = self._store.popitem(last=False)
                self._total_bytes -= len(removed)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._total_bytes = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"items": len(self._store), "bytes": self._total_bytes}


GLOBAL_RESULT_CACHE = ResultCache(max_items=64)
