"""Self-retune pipeline — the bot proposes its own upgrades, with evidence.

Closes the loop from "the strategy is degrading" to "here is a validated
replacement auditioning right now":

    1. TRIGGER   the live track record diverges from the backtest promise
                 (or a human calls POST /research/retune)
    2. SEARCH    a small grid of Decision Brain configs (conviction × RR) is
                 evaluated on REAL cached candles with a train/test split —
                 candidates are ranked on the TRAIN slice only
    3. VALIDATE  the best candidate must beat the incumbent on the UNSEEN
                 test slice by a real margin, across symbols
    4. AUDITION  the winner auto-starts as a shadow on live candles and
                 Telegram gets the news; PROMOTION STAYS HUMAN — the shadow
                 report says when the evidence justifies switching

No real data cached -> it says so and does nothing. No candidate beats the
incumbent -> verdict "keep-incumbent" with the numbers shown. The bot never
silently changes its own live strategy.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# the search space: small on purpose — a wide grid on one dataset is how
# overfitting happens. Incumbent defaults are conviction 0.56 / RR 3.0.
CONVICTIONS = (0.50, 0.56, 0.62)
RR_TARGETS = (2.5, 3.0, 3.5)
INCUMBENT = {"conviction_threshold": 0.56, "rr_target": 3.0}
MIN_TEST_TRADES = 8          # per symbol, on the test slice
BEAT_MARGIN = 1.10           # candidate must beat incumbent test net R by 10%


def _run_config(symbol: str, rows, params: dict) -> dict:
    from strategies.brain_strategy import DecisionBrain
    from strategies.custom import simulate_strategy
    strat = DecisionBrain(symbol, **params)
    res = simulate_strategy(strat, rows)
    return {"trades": res.get("total_trades", 0), "net_r": res.get("net_r", 0.0),
            "win_rate": res.get("win_rate", 0.0),
            "profit_factor": res.get("profit_factor", 0.0)}


def evaluate_candidates(symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"),
                        timeframe: str = "4h", bars: int = 4000,
                        split: float = 0.7, require_real: bool = True) -> dict:
    """Grid-search brain configs on train slices; validate the best on the
    unseen test slices vs the incumbent. Pure decision logic, honest verdicts."""
    from data.market_data import get_bars

    data = {}
    for sym in symbols:
        rows, src = get_bars(sym, n=bars, timeframe=timeframe, require_real=require_real)
        if rows and len(rows) >= 600:
            cut = int(len(rows) * split)
            data[sym] = {"train": rows[:cut], "test": rows[cut:], "source": src}
    if not data:
        return {"available": False, "verdict": "no-real-data",
                "detail": "No real candles cached — run POST /data/backfill first."}

    grid = [{"conviction_threshold": c, "rr_target": r}
            for c in CONVICTIONS for r in RR_TARGETS
            if {"conviction_threshold": c, "rr_target": r} != INCUMBENT]

    # rank candidates on TRAIN only (never let the test slice pick the winner)
    ranked = []
    for params in grid:
        train_net = sum(_run_config(s, d["train"], params)["net_r"]
                        for s, d in data.items())
        ranked.append((train_net, params))
    ranked.sort(key=lambda x: -x[0])
    best_params = ranked[0][1]

    # the unseen test slice decides: candidate vs incumbent, per symbol
    per_symbol = []
    cand_total = inc_total = 0.0
    enough = True
    for sym, d in data.items():
        cand = _run_config(sym, d["test"], best_params)
        inc = _run_config(sym, d["test"], INCUMBENT)
        cand_total += cand["net_r"]
        inc_total += inc["net_r"]
        if cand["trades"] < MIN_TEST_TRADES:
            enough = False
        per_symbol.append({"symbol": sym, "candidate": cand, "incumbent": inc,
                           "data_source": d["source"]})

    beats = cand_total > max(inc_total * BEAT_MARGIN, inc_total + 2.0)
    if not enough:
        verdict, detail = "insufficient-trades", \
            f"Best candidate produced <{MIN_TEST_TRADES} test trades on some symbol — not judged."
    elif beats:
        verdict, detail = "candidate-found", \
            (f"Candidate {best_params} beats the incumbent on unseen data: "
             f"{cand_total:+.1f}R vs {inc_total:+.1f}R — audition it in shadow mode.")
    else:
        verdict, detail = "keep-incumbent", \
            (f"No candidate beat the incumbent on unseen data "
             f"(best {cand_total:+.1f}R vs incumbent {inc_total:+.1f}R). Keep the current brain.")
    return {"available": True, "verdict": verdict, "detail": detail,
            "best_candidate": best_params, "incumbent": INCUMBENT,
            "test_net_r": {"candidate": round(cand_total, 2),
                           "incumbent": round(inc_total, 2)},
            "per_symbol": per_symbol,
            "train_ranking": [{"params": p, "train_net_r": round(n, 2)}
                              for n, p in ranked[:5]],
            "ran_at": datetime.now(timezone.utc).isoformat()}


def retune(engine, notifier=None, *, timeframe: str = "4h",
           track_verdict: Optional[str] = None, force: bool = False,
           require_real: bool = True) -> dict:
    """The full loop: run the search and, when a validated candidate exists,
    auto-start it as a shadow on the live engine + notify. Promotion is human."""
    if not force and track_verdict not in ("diverging",):
        return {"ran": False,
                "detail": f"Track record is '{track_verdict}' — retune runs only on "
                          f"divergence (or force=true)."}
    report = evaluate_candidates(symbols=tuple(engine.symbols),
                                 timeframe=timeframe, require_real=require_real)
    report["ran"] = True
    if report.get("verdict") != "candidate-found":
        return report

    from services.shadow import ShadowRun
    from strategies.brain_strategy import DecisionBrain
    params = report["best_candidate"]

    def factory(sym: str):
        return DecisionBrain(sym, **params)

    label = (f"Retuned brain (conv {params['conviction_threshold']}, "
             f"RR {params['rr_target']})")
    engine.shadow = ShadowRun(label, factory, engine.symbols)
    report["shadow_started"] = label
    if notifier is not None:
        try:
            notifier("risk", "🔧 Retune candidate found",
                     f"{report['detail']} Now auditioning as a shadow — promotion "
                     f"stays manual (see /shadow/report).")
        except Exception:  # noqa: BLE001
            pass
    return report
