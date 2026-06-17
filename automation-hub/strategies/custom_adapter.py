"""Run a user-built custom strategy spec inside the live (paper) engine.

Wraps a custom rule spec as a HubStrategy so the autonomous engine can paper-
trade it — the bridge from the Strategy Builder to paper trading. The pipeline
still applies all risk checks (market quality, sizing, exposure, drawdown halt).
"""
from __future__ import annotations

from typing import Optional

from bot.types import Bar, Signal, SignalType
from strategies.base_strategy import HubStrategy
from strategies.custom import WARMUP, _stop_distance, _target_distance, evaluate


class CustomStrategyAdapter(HubStrategy):
    name = "custom"
    label = "Custom"

    def __init__(self, symbol: str, spec: dict, *, max_history: int = 700, **params):
        target = spec.get("target") or {}
        params.setdefault("rr_target", float(target.get("rr", 1.5)) if target.get("type", "rr") == "rr" else 1.5)
        super().__init__(symbol, **params)
        self.spec = spec
        self.max_history = max_history
        self.label = f"Custom: {spec.get('name', 'Strategy')}"

    def generate(self, bar: Bar) -> Optional[Signal]:
        if len(self.bars) > self.max_history:
            del self.bars[:-self.max_history]
        if len(self.bars) < WARMUP:
            return None
        i = len(self.bars) - 1
        entry_tree = self.spec.get("entry") or {"op": "AND", "rules": []}
        matched, reasons = evaluate(entry_tree, self.bars, i)
        if not matched:
            return None

        side = self.spec.get("side", "long")
        entry = bar.close
        risk_abs = _stop_distance(self.spec.get("stop") or {}, entry, self.bars, i)
        if risk_abs <= 0:
            return None
        tgt = _target_distance(self.spec.get("target") or {}, risk_abs, entry)
        if side == "long":
            direction, stop, take = SignalType.LONG, entry - risk_abs, entry + tgt
        else:
            direction, stop, take = SignalType.SHORT, entry + risk_abs, entry - tgt

        sig = Signal(timestamp=bar.timestamp, symbol=self.symbol, type=direction,
                     entry=entry, stop_loss=stop, take_profit=take,
                     reason="; ".join(reasons) or "custom entry")
        sig.confidence = 1.0
        return sig
