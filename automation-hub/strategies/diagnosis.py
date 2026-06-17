"""Post-simulation diagnosis — explains why trades won/lost in plain terms.

Pure function over the simulator's output (taken trades + blocked setups). No
fabrication: every figure is derived from the trades that actually happened.
"""
from __future__ import annotations

from collections import Counter
from statistics import mean


def _hour(ts: str) -> int:
    try:
        return int(ts.split("T")[1][:2])
    except Exception:  # noqa: BLE001
        return -1


def _session(hour: int) -> str:
    if hour < 0:
        return "unknown"
    if 0 <= hour < 8:
        return "Asia"
    if 8 <= hour < 16:
        return "London"
    return "New York"


def diagnose(results: dict, blocked: list | None = None) -> dict:
    trades = results.get("trades") or []
    blocked = blocked or []
    n = len(trades)
    if n == 0:
        rec = ("Every candidate setup was blocked by the quality filter — loosen the "
               "minimum score or entry rules if this is too strict."
               if blocked else
               "No setups matched the entry rules over this period — the rules may be too restrictive.")
        return {
            "summary": "No trades were taken in this simulation.",
            "headline_problem": "No setups passed the entry rules and quality gate.",
            "loss_reasons": {}, "blocked_reasons": _count_blocked(blocked),
            "blocked_count": len(blocked),
            "worst_regime": None, "worst_session": None,
            "overtrading": False, "choppy_markets": False, "recommendations": [rec],
        }

    wins = [t for t in trades if t.get("r", 0) > 0]
    losses = [t for t in trades if t.get("r", 0) <= 0]

    # which entry rule appears most often in losing trades
    loss_rule_counter: Counter = Counter()
    for t in losses:
        for part in str(t.get("reason", "")).split(";"):
            part = part.strip()
            if part:
                loss_rule_counter[part] += 1

    # regime / session performance
    reg_pnl: dict = {}
    sess_pnl: dict = {}
    for t in trades:
        reg = t.get("regime", "unknown")
        reg_pnl.setdefault(reg, []).append(t.get("r", 0))
        s = _session(_hour(t.get("entry_time", "")))
        sess_pnl.setdefault(s, []).append(t.get("r", 0))
    worst_regime = _worst(reg_pnl)
    worst_session = _worst(sess_pnl)

    # exit-reason / stop-hit pattern
    exit_counter = Counter(t.get("exit_reason", "target/stop") for t in trades)
    stop_hits = sum(1 for t in losses if t.get("exit_reason") in (None, "stop", "target/stop"))

    # how good were the losing setups (low score = bad location)
    scored = [t.get("score") for t in trades if t.get("score") is not None]
    avg_score = round(mean(scored), 1) if scored else None
    avg_loss_score = round(mean([t["score"] for t in losses if t.get("score") is not None]), 1) \
        if any(t.get("score") is not None for t in losses) else None

    avg_rr = round(mean([abs(t.get("r", 0)) for t in wins]) /
                   (mean([abs(t.get("r", 0)) for t in losses]) or 1), 2) if wins and losses else None

    # behaviour flags
    span_days = max(1, results.get("span_days", 1))
    per_day = n / span_days
    overtrading = per_day > 3
    choppy = (results.get("win_rate", 0) < 45 and
              sum(len(v) for k, v in reg_pnl.items() if k in ("Ranging", "High Volatility", "Extreme Volatility"))
              > n * 0.5)

    recs = _recommendations(results, worst_regime, overtrading, choppy, avg_loss_score, avg_rr, blocked)

    return {
        "summary": (f"{n} trades · {len(wins)} wins / {len(losses)} losses · "
                    f"win rate {results.get('win_rate', 0)}% · profit factor "
                    f"{results.get('profit_factor', 0)}."),
        "headline_problem": recs[0] if recs else "No dominant problem detected.",
        "avg_quality_score": avg_score,
        "avg_losing_setup_score": avg_loss_score,
        "loss_reasons": dict(loss_rule_counter.most_common(6)),
        "blocked_reasons": _count_blocked(blocked),
        "blocked_count": len(blocked),
        "worst_regime": worst_regime,
        "worst_session": worst_session,
        "exit_pattern": dict(exit_counter),
        "stop_hit_losses": stop_hits,
        "avg_win_to_loss": avg_rr,
        "overtrading": overtrading,
        "trades_per_day": round(per_day, 2),
        "choppy_markets": choppy,
        "recommendations": recs,
    }


def _count_blocked(blocked: list) -> dict:
    c: Counter = Counter()
    for b in blocked:
        for reason in (b.get("blocks") or [b.get("reason", "blocked")]):
            # keep the reason short (first clause)
            c[str(reason).split("(")[0].strip()] += 1
    return dict(c.most_common(8))


def _worst(group: dict):
    if not group:
        return None
    worst = min(group.items(), key=lambda kv: sum(kv[1]))
    name, rs = worst
    return {"name": name, "trades": len(rs), "net_r": round(sum(rs), 2),
            "win_rate": round(100 * sum(1 for r in rs if r > 0) / len(rs), 0) if rs else 0}


def _recommendations(results, worst_regime, overtrading, choppy, avg_loss_score, avg_rr, blocked) -> list:
    recs: list = []
    pf = results.get("profit_factor", 0)
    wr = results.get("win_rate", 0)
    if pf < 1:
        recs.append("Strategy is unprofitable in simulation — tighten entries with the quality filter "
                    "and trade only supported regimes.")
    if choppy:
        recs.append("More than half the trades fired in ranging/volatile regimes — add a trend/regime "
                    "filter or raise the minimum trade-quality score.")
    if worst_regime and worst_regime["net_r"] < 0:
        recs.append(f"Worst regime is {worst_regime['name']} "
                    f"({worst_regime['net_r']}R over {worst_regime['trades']} trades) — avoid it.")
    if avg_loss_score is not None and avg_loss_score < 60:
        recs.append(f"Losing trades averaged a quality score of {avg_loss_score}/100 — raising the "
                    "minimum score would have skipped most of them.")
    if avg_rr is not None and avg_rr < 1:
        recs.append("Average win is smaller than average loss — increase the reward:risk target or "
                    "use break-even/trailing exits to protect winners.")
    if wr > 55 and pf < 1.1:
        recs.append("High win rate but weak profit factor — small wins and big losses; widen targets "
                    "or cut losers earlier.")
    if overtrading:
        recs.append("Trade frequency is high — overtrading erodes edge through costs; tighten filters.")
    if len(blocked) > results.get("total_trades", 0):
        recs.append(f"The brain blocked {len(blocked)} weak setups — avoiding those is part of the edge.")
    if not recs:
        recs.append("No dominant problem detected. Validate on out-of-sample data and in paper trading.")
    return recs
