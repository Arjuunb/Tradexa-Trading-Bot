"""Tiny TTL cache for expensive analysis endpoints.

The dashboard polls analysis routes (strategy league, marketplace ranking)
that each run many full simulations. On a small instance an uncached poll can
stall the API for tens of seconds and starve the trading engine's thread.
Successful results are cached for a short TTL keyed by the request params;
errors and unavailable results are NOT cached, so recovery is immediate.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

_lock = threading.Lock()
_store: dict = {}


def cached(key: str, ttl: float, fn: Callable[[], dict]) -> dict:
    now = time.time()
    with _lock:
        hit = _store.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    result = fn()
    # only cache genuine results — failures must retry on the next call
    if isinstance(result, dict) and result.get("available") is not False and "error" not in result:
        with _lock:
            _store[key] = (now, result)
            if len(_store) > 200:
                oldest = min(_store, key=lambda k: _store[k][0])
                _store.pop(oldest, None)
    return result


def clear() -> None:
    with _lock:
        _store.clear()
