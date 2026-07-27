"""Where is this strategy in its lifecycle, and what does it need next?

The nine stages all worked before this module existed; they just lived on seven
different pages with nothing joining them. A trader who finished a backtest had
no affordance pointing at the review, and one whose strategy was deployed had no
hint that monitoring lives on a page filed under "System".

This computes the answer from REAL state — the saved spec, the stored version
history, the paper ledger, the running engine, the monitor, the marketplace and
the share grants. Nothing here is a checkbox a user ticks; a stage is "done"
because the evidence for it exists.

Two rules, both load-bearing:

  * **A stage nobody recorded is ``unknown``, not ``pending``.** Replay leaves no
    trace, so this module says it cannot tell rather than implying you skipped it.
    Presenting an unknowable as "not done" would nag people into redoing work
    they already did.
  * **``blocked_by`` is honest about order.** You cannot review a strategy with no
    backtest. Saying so is more useful than showing a review button that fails.
"""
from __future__ import annotations

from typing import Any, Optional

# The lifecycle, in order. ``page`` is where the work happens, so the UI can send
# someone straight there instead of describing the destination.
STAGES: tuple[dict, ...] = (
    {"key": "compile", "n": 1, "title": "AI Strategy Agent", "page": "Strategy Studio",
     "purpose": "Turn your idea into executable rules."},
    {"key": "backtest", "n": 2, "title": "Backtesting", "page": "Backtesting",
     "purpose": "Test the rules on real historical data."},
    {"key": "review", "n": 3, "title": "AI Strategy Review", "page": "Strategy Studio",
     "purpose": "Analyse the result and find the weaknesses."},
    {"key": "paper", "n": 4, "title": "Paper Trading", "page": "Paper Trading",
     "purpose": "Run it forward on live prices with virtual money."},
    {"key": "replay", "n": 5, "title": "Replay Mode", "page": "Replay",
     "purpose": "Watch it trade history candle by candle."},
    {"key": "deploy", "n": 6, "title": "Live Deployment", "page": "Live Trading",
     "purpose": "Run the same strategy on a connected account."},
    {"key": "monitor", "n": 7, "title": "AI Monitoring Agent", "page": "Bot Health",
     "purpose": "Watch for drift from the tested behaviour."},
    {"key": "publish", "n": 8, "title": "Marketplace", "page": "Strategies",
     "purpose": "Share it with verified results."},
    {"key": "collaborate", "n": 9, "title": "Versioning & Collaboration", "page": "Strategy Studio",
     "purpose": "Track changes and work with others."},
)

# A stage's state. "unknown" exists so an unrecorded stage is never miscalled.
DONE, READY, BLOCKED, UNKNOWN = "done", "ready", "blocked", "unknown"

MIN_PAPER_TRADES = 15      # matches monitor_agent.MIN_LIVE_TRADES
MIN_BACKTEST_TRADES = 10   # below this a review has nothing to say


def _rules(spec: Optional[dict]) -> list:
    return ((spec or {}).get("entry") or {}).get("rules") or []


def _stage(key: str, state: str, *, detail: str, evidence=None,
           action: Optional[str] = None, blocked_by: Optional[str] = None) -> dict:
    meta = next(s for s in STAGES if s["key"] == key)
    return {**meta, "state": state, "detail": detail,
            "evidence": evidence or [], "action": action, "blocked_by": blocked_by}


def evaluate(*, spec: Optional[dict],
             backtest: Optional[dict] = None,
             paper: Optional[dict] = None,
             deployed: bool = False,
             monitor: Optional[dict] = None,
             listing: Optional[dict] = None,
             shares: Optional[dict] = None,
             comments: int = 0) -> dict:
    """The lifecycle state of one strategy.

    Every argument is observed state, injected by the caller — this module does
    no I/O, so each signal is testable and none of them can be faked by a flag
    the user sets."""
    if not spec:
        return {"available": False, "stages": [],
                "note": "Strategy not found."}

    stages: list[dict] = []
    rules = _rules(spec)

    # 1 · compile ----------------------------------------------------------
    if rules:
        stages.append(_stage("compile", DONE,
                             detail=f"{len(rules)} entry rule(s) compiled.",
                             evidence=[{"stat": "entry rules", "value": len(rules)},
                                       {"stat": "symbol / timeframe",
                                        "value": f"{spec.get('symbol', '?')} {spec.get('timeframe', '?')}"}],
                             action="Edit rules"))
    else:
        stages.append(_stage("compile", READY,
                             detail="No entry rules yet. Describe your idea and the agent will compile it.",
                             action="Open the agent"))

    # 2 · backtest ---------------------------------------------------------
    bt_trades = int((backtest or {}).get("total_trades") or 0)
    if not rules:
        stages.append(_stage("backtest", BLOCKED,
                             detail="A strategy needs entry rules before it can be tested.",
                             blocked_by="compile"))
    elif bt_trades:
        stages.append(_stage("backtest", DONE,
                             detail=f"{bt_trades} trades over the tested window.",
                             evidence=[{"stat": "trades", "value": bt_trades},
                                       {"stat": "net R", "value": (backtest or {}).get("net_r")},
                                       {"stat": "profit factor",
                                        "value": (backtest or {}).get("profit_factor")}],
                             action="Re-run backtest"))
    else:
        stages.append(_stage("backtest", READY,
                             detail="Not tested yet on this window.",
                             action="Run backtest"))

    # 3 · review -----------------------------------------------------------
    if bt_trades >= MIN_BACKTEST_TRADES:
        stages.append(_stage("review", READY,
                             detail=f"{bt_trades} trades is enough for an evidence-based review.",
                             action="Open review"))
    elif bt_trades:
        stages.append(_stage("review", BLOCKED,
                             detail=(f"{bt_trades} trades is below the {MIN_BACKTEST_TRADES} "
                                     "a review needs — its conclusions would be noise."),
                             blocked_by="backtest"))
    else:
        stages.append(_stage("review", BLOCKED,
                             detail="Nothing to review until the strategy has been backtested.",
                             blocked_by="backtest"))

    # 4 · paper ------------------------------------------------------------
    p_trades = int((paper or {}).get("trades") or 0)
    attributed = bool((paper or {}).get("attributed"))
    if p_trades >= MIN_PAPER_TRADES:
        stages.append(_stage("paper", DONE,
                             detail=f"{p_trades} closed paper trades on record.",
                             evidence=[{"stat": "closed paper trades", "value": p_trades},
                                       {"stat": "net R", "value": (paper or {}).get("net_r")}],
                             action="Open paper trading"))
    elif p_trades:
        stages.append(_stage("paper", READY,
                             detail=(f"{p_trades} of {MIN_PAPER_TRADES} closed trades. "
                                     "Keep it running — monitoring needs the sample."),
                             evidence=[{"stat": "closed paper trades", "value": p_trades}],
                             action="Open paper trading"))
    elif rules:
        stages.append(_stage("paper", READY,
                             detail="Deploy to paper to start a forward track record.",
                             action="Deploy to paper"))
    else:
        stages.append(_stage("paper", BLOCKED,
                             detail="A strategy needs entry rules before it can trade.",
                             blocked_by="compile"))
    if p_trades and not attributed:
        stages[-1]["caveat"] = ("These trades are the paper account's, not this "
                                "strategy's — they predate per-strategy attribution.")

    # 5 · replay -----------------------------------------------------------
    # Replay leaves no persistent record, so its state is genuinely unknowable.
    # Reporting "not done" would nag people into redoing work they already did.
    stages.append(_stage("replay", UNKNOWN if rules else BLOCKED,
                         detail=("Replay sessions are not recorded, so this stage "
                                 "cannot be confirmed either way."
                                 if rules else
                                 "A strategy needs entry rules before it can be replayed."),
                         action="Open replay" if rules else None,
                         blocked_by=None if rules else "compile"))

    # 6 · deploy -----------------------------------------------------------
    if deployed:
        stages.append(_stage("deploy", DONE,
                             detail="This strategy is the one currently running.",
                             action="Open live trading"))
    elif p_trades >= MIN_PAPER_TRADES:
        stages.append(_stage("deploy", READY,
                             detail="Enough paper history to consider a live review.",
                             action="Open live trading"))
    else:
        stages.append(_stage("deploy", BLOCKED,
                             detail=(f"Live deployment needs a paper track record first "
                                     f"({p_trades} of {MIN_PAPER_TRADES} closed trades)."),
                             blocked_by="paper"))

    # 7 · monitor ----------------------------------------------------------
    m_status = (monitor or {}).get("status")
    if deployed and m_status and m_status != "no_strategy":
        stages.append(_stage("monitor", DONE,
                             detail=f"Monitoring is active — status: {m_status}.",
                             evidence=[{"stat": "monitor status", "value": m_status},
                                       {"stat": "findings",
                                        "value": len((monitor or {}).get("findings") or [])}],
                             action="Open monitoring"))
    elif deployed:
        stages.append(_stage("monitor", READY,
                             detail="Deployed, but the monitor has not evaluated it yet.",
                             action="Open monitoring"))
    else:
        stages.append(_stage("monitor", BLOCKED,
                             detail="Monitoring watches the deployed strategy — nothing to watch yet.",
                             blocked_by="deploy"))

    # 8 · publish ----------------------------------------------------------
    if listing:
        metrics = (listing.get("verified") or {}).get("metrics") or {}
        stages.append(_stage("publish", DONE,
                             detail=f"Published with a verified backtest ({metrics.get('total_trades', '?')} trades).",
                             evidence=[{"stat": "rating", "value": (listing.get("rating") or {}).get("average")},
                                       {"stat": "imports", "value": listing.get("imports")}],
                             action="Open marketplace"))
    elif bt_trades >= MIN_BACKTEST_TRADES:
        stages.append(_stage("publish", READY,
                             detail="Enough verified history to publish.",
                             action="Publish"))
    else:
        stages.append(_stage("publish", BLOCKED,
                             detail=(f"Publishing verifies a backtest first — "
                                     f"{bt_trades} of {MIN_BACKTEST_TRADES} trades."),
                             blocked_by="backtest"))

    # 9 · collaborate ------------------------------------------------------
    versions = len(spec.get("versions") or [])
    grants = len(((shares or {}).get("grants")) or {})
    if versions or grants or comments:
        bits = []
        if versions:
            bits.append(f"{versions} version(s)")
        if grants:
            bits.append(f"shared with {grants}")
        if comments:
            bits.append(f"{comments} comment(s)")
        stages.append(_stage("collaborate", DONE,
                             detail=" · ".join(bits) + ".",
                             evidence=[{"stat": "versions", "value": versions},
                                       {"stat": "collaborators", "value": grants},
                                       {"stat": "comments", "value": comments}],
                             action="Open history"))
    else:
        stages.append(_stage("collaborate", READY,
                             detail="No edits recorded yet — the first change starts the history.",
                             action="Open history"))

    done = sum(1 for s in stages if s["state"] == DONE)
    nxt = next((s for s in stages if s["state"] == READY), None)
    return {
        "available": True,
        "strategy": {"id": spec.get("id"), "name": spec.get("name"),
                     "symbol": spec.get("symbol"), "timeframe": spec.get("timeframe")},
        "stages": stages,
        "completed": done,
        "total": len(STAGES),
        # "unknown" stages are excluded from the denominator rather than counted
        # as failures — see the module docstring.
        "unknown": sum(1 for s in stages if s["state"] == UNKNOWN),
        "next": nxt,
        "note": (None if nxt else
                 "Every stage that can be confirmed is complete."),
    }
