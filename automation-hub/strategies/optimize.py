"""Careful, anti-overfitting optimisation via a train/test split.

Optimises only a few brain-relevant knobs (minimum quality score, reward:risk
target, ATR stop multiplier) on the FIRST part of the data, then validates the
chosen setting on the UNSEEN second part. Results are flagged reliable ONLY when
the out-of-sample period also improves — otherwise it's reported as overfit.

Pure logic over the existing `simulate()`; no I/O.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Sequence

from strategies.brain import TradeBrain
from strategies.custom import simulate

# Small, sane grids — kept tiny on purpose to limit overfitting surface.
DEFAULT_GRID = {
    "min_score": [50, 60, 70],
    "rr": [1.5, 2.0, 2.5],
    "stop_mult": [1.2, 1.5, 2.0],
}


def _apply(spec: dict, min_score: int, rr: float, stop_mult: float) -> dict:
    s = deepcopy(spec)
    s.setdefault("target", {})
    s["target"] = {"type": "rr", "rr": rr}
    s.setdefault("stop", {})
    st = dict(s.get("stop") or {})
    st.update({"type": "atr", "mult": stop_mult, "period": int(st.get("period", 14))})
    s["stop"] = st
    return s


def _score_metric(res: dict) -> float:
    """Rank candidates by net R, but require a minimum sample size so we don't
    pick a lucky 3-trade run."""
    n = res.get("total_trades", 0)
    if n < 10:
        return -1e9 + n  # heavily penalise too-few-trades, but keep ordering
    return res.get("net_r", 0.0)


def walk_forward(spec: dict, bars: Sequence, *, grid: dict | None = None,
                 split: float = 0.7) -> dict:
    """Optimise on the train slice, validate on the unseen test slice."""
    grid = grid or DEFAULT_GRID
    cut = int(len(bars) * split)
    train, test = list(bars[:cut]), list(bars[cut:])
    brain = TradeBrain()

    # baseline = the strategy as-is, brain on, default min score 60
    base_train = simulate(spec, train, brain=brain, min_score=60)
    base_test = simulate(spec, test, brain=brain, min_score=60)

    best = None
    trials = []
    for ms in grid["min_score"]:
        for rr in grid["rr"]:
            for sm in grid["stop_mult"]:
                cand = _apply(spec, ms, rr, sm)
                rtr = simulate(cand, train, brain=brain, min_score=ms)
                metric = _score_metric(rtr)
                trials.append({"min_score": ms, "rr": rr, "stop_mult": sm,
                               "train_net_r": rtr.get("net_r", 0), "train_pf": rtr.get("profit_factor", 0),
                               "train_trades": rtr.get("total_trades", 0)})
                if best is None or metric > best["metric"]:
                    best = {"params": (ms, rr, sm), "metric": metric, "train": rtr}

    ms, rr, sm = best["params"]
    best_spec = _apply(spec, ms, rr, sm)
    val = simulate(best_spec, test, brain=brain, min_score=ms)

    # Honest verdict: the chosen params must beat the baseline OUT OF SAMPLE.
    improved_oos = (val.get("net_r", 0) > base_test.get("net_r", 0)
                    and val.get("profit_factor", 0) >= base_test.get("profit_factor", 0)
                    and val.get("total_trades", 0) >= 10)
    if improved_oos and val.get("profit_factor", 0) >= 1:
        verdict = "reliable"
        note = "Out-of-sample validation also improved — safe to consider for paper trading."
    elif improved_oos:
        verdict = "marginal"
        note = "Validation improved but stays below profit factor 1 — not yet trustworthy."
    else:
        verdict = "overfit"
        note = ("Optimised settings did NOT improve on unseen data — likely overfit. "
                "Do not trust the train numbers.")

    return {
        "best_params": {"min_score": ms, "rr": rr, "stop_mult": sm},
        "train": {"net_r": best["train"].get("net_r"), "profit_factor": best["train"].get("profit_factor"),
                  "win_rate": best["train"].get("win_rate"), "trades": best["train"].get("total_trades")},
        "validation": {"net_r": val.get("net_r"), "profit_factor": val.get("profit_factor"),
                       "win_rate": val.get("win_rate"), "trades": val.get("total_trades")},
        "baseline_validation": {"net_r": base_test.get("net_r"), "profit_factor": base_test.get("profit_factor"),
                                "trades": base_test.get("total_trades")},
        "baseline_train": {"net_r": base_train.get("net_r"), "profit_factor": base_train.get("profit_factor")},
        "verdict": verdict, "note": note,
        "split": split, "train_bars": len(train), "test_bars": len(test),
        "trials": sorted(trials, key=lambda t: t["train_net_r"], reverse=True)[:9],
    }
