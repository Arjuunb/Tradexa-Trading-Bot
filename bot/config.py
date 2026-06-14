"""YAML config loader.

Builds a broker, strategy, risk manager, and (for backtests) a Backtester from
``configs/*.yaml`` so users don't have to edit Python to change parameters.

Env-var substitution
--------------------
Any string value matching ``${VAR_NAME}`` is replaced with ``os.environ[VAR_NAME]``.
This lets users keep API keys out of YAML files.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from bot.brokers import get_broker
from bot.risk import RiskConfig, RiskManager
from bot.strategies import SupportResistanceRejection


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _substitute_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            return os.environ.get(m.group(1), "")
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    return value


def load_yaml(path: str | Path) -> dict:
    try:
        import yaml
    except ImportError as e:
        raise ImportError(
            "Install pyyaml to use the config loader: pip install pyyaml"
        ) from e
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _substitute_env(raw)


# --------------------------------------------------------------- factories
_STRATEGY_REGISTRY = {
    "support_resistance_rejection": SupportResistanceRejection,
}


def build_from_config(cfg: dict):
    """Returns (broker, strategy, risk, meta) where meta has keys
    symbol/timeframe/mode/dry_run/warmup_bars."""
    bcfg = cfg.get("broker", {})
    venue = bcfg.pop("venue", "paper")
    broker = get_broker(venue, **bcfg)

    symbol = cfg["symbol"]
    timeframe = cfg.get("timeframe", "1h")

    scfg = cfg.get("strategy", {}) or {}
    sname = scfg.get("name", "support_resistance_rejection")
    if sname not in _STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy: {sname}")
    strategy = _STRATEGY_REGISTRY[sname](symbol=symbol, **(scfg.get("params") or {}))

    risk_cfg = RiskConfig(**(cfg.get("risk") or {}))
    risk = RiskManager(risk_cfg)

    meta = {
        "symbol": symbol,
        "timeframe": timeframe,
        "warmup_bars": cfg.get("warmup_bars", 200),
        "mode": cfg.get("mode", "paper"),
        "dry_run": bool(cfg.get("dry_run", False)),
        "market": cfg.get("market", "24_7"),
    }
    return broker, strategy, risk, meta
