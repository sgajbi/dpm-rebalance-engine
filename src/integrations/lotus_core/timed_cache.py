from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Callable, Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True)
class TimedCacheStats:
    hits: int
    misses: int
    expirations: int
    writes: int
    evictions: int
    size: int


class TimedCache(Generic[K, V]):
    def __init__(
        self,
        *,
        clone_value: Callable[[V], V],
        ttl_seconds: Callable[[], float],
        max_size: Callable[[], int],
    ) -> None:
        self._clone_value = clone_value
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._lock = RLock()
        self._values: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._expirations = 0
        self._writes = 0
        self._evictions = 0

    def get(self, key: K) -> V | None:
        now = time.monotonic()
        with self._lock:
            cached_entry = self._values.get(key)
            if cached_entry is None:
                self._misses += 1
                return None
            expires_at, value = cached_entry
            if expires_at <= now:
                self._values.pop(key, None)
                self._misses += 1
                self._expirations += 1
                return None
            self._values.move_to_end(key)
            self._hits += 1
            return self._clone_value(value)

    def set(self, key: K, value: V) -> V:
        with self._lock:
            self._values[key] = (
                time.monotonic() + self._ttl_seconds(),
                self._clone_value(value),
            )
            self._writes += 1
            self._values.move_to_end(key)
            while len(self._values) > self._max_size():
                self._values.popitem(last=False)
                self._evictions += 1
        return self._clone_value(value)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._hits = 0
            self._misses = 0
            self._expirations = 0
            self._writes = 0
            self._evictions = 0

    def stats(self) -> TimedCacheStats:
        with self._lock:
            return TimedCacheStats(
                hits=self._hits,
                misses=self._misses,
                expirations=self._expirations,
                writes=self._writes,
                evictions=self._evictions,
                size=len(self._values),
            )
