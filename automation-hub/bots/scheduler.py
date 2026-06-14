"""Bot scheduler — Phase 2 interface.

Drives running bots on a cadence: on each new closed bar (from data.websocket),
feed the strategy, route signals through risk + execution. Phase 1 runs are
one-shot paper simulations, so this is the live-loop seam, defined now.
"""
from __future__ import annotations

import threading
from typing import Callable

Tick = Callable[[], None]


class Scheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, tick: Tick, interval_s: float = 60.0) -> None:  # pragma: no cover
        def _loop() -> None:
            while not self._stop.wait(interval_s):
                try:
                    tick()
                except Exception:  # noqa: BLE001 - a bad tick must not kill the loop
                    pass
        self._stop.clear()
        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
