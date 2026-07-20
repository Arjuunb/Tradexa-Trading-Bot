"""Analytics endpoints — split from webhook_api.py.

Endpoint bodies are unchanged except that references to shared state resolve via
``_wa.<name>`` so singletons (pipeline, ledger, paper, engine, …) are read from
webhook_api at request time. That keeps the test suite's fixture rebinding
(``webhook_api.pipeline = <fresh>``) working exactly as before the split.
"""
import webhook_api as _wa
from fastapi import APIRouter, Header, HTTPException, Body, Query, Depends  # noqa: F401
from typing import Optional, List, Dict  # noqa: F401

# Fallback: expose every webhook_api global by name so references the qualifier
# intentionally left bare (e.g. inside f-strings) still resolve. Qualified
# `_wa.<name>` uses stay dynamic; these copies are only a safety net.
globals().update({k: v for k, v in vars(_wa).items()
                  if not k.startswith("__") and k != "router"})

router = APIRouter()


@router.get("/coach/review")
def coach_review_endpoint(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                          timeframe: str = "15m", limit: int = 800):
    """AI Trading Coach — a mentor-style review of a REAL replay run: why trades
    won / lost, the recurring mistakes, weak conditions, suggestions, plus
    performance attribution and per-trade explanations."""
    from services.replay import build_replay
    from services.coach import coach_review
    rep = build_replay(symbol, timeframe, limit, strategy=strategy)
    if rep["meta"]["bars"] == 0:
        return {"available": False, "error": rep["meta"].get("data_warning", "No data."),
                "needs_download": rep["meta"].get("needs_download", False)}
    review = coach_review(rep["trades"], rep["stats"], symbol=symbol, strategy=strategy)
    review["available"] = True
    review["data_source"] = rep["meta"]["data_source_label"]
    return review

@router.get("/coach/leaderboard")
def coach_leaderboard(symbols: str = "BTCUSDT,ETHUSDT", strategies: str = "Decision Brain,EMA 20/50,Supply/Demand",
                      timeframe: str = "15m", limit: int = 600):
    """Performance attribution across strategies × symbols — which strategy and
    which symbol actually made money (#17). Runs real replays."""
    from services.replay import build_replay
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:4]
    strats = [s.strip() for s in strategies.split(",") if s.strip()][:5]
    grid, by_strategy, by_symbol = [], {}, {}
    for st in strats:
        for sym in syms:
            rep = build_replay(sym, timeframe, limit, strategy=st)
            s = rep["stats"]
            row = {"strategy": st, "symbol": sym, "trades": s["trades"],
                   "win_rate": s["win_rate"], "profit_factor": s["profit_factor"], "net_r": s["net_r"]}
            grid.append(row)
            by_strategy[st] = round(by_strategy.get(st, 0.0) + s["net_r"], 2)
            by_symbol[sym] = round(by_symbol.get(sym, 0.0) + s["net_r"], 2)
    grid.sort(key=lambda r: r["net_r"], reverse=True)
    rank = lambda d: sorted(({"key": k, "net_r": v} for k, v in d.items()), key=lambda x: x["net_r"], reverse=True)
    return {"timeframe": timeframe, "grid": grid,
            "by_strategy": rank(by_strategy), "by_symbol": rank(by_symbol),
            "best": grid[0] if grid else None}

@router.get("/lab/walk-forward")
def lab_walk_forward(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                     timeframe: str = "4h", bars: int = 4000, folds: int = 4):
    """Walk-forward: optimise per train block, validate on the next unseen block."""
    from services.backtest_lab import walk_forward
    return walk_forward(strategy, symbol, timeframe, bars=bars, folds=folds)

@router.get("/lab/monte-carlo")
def lab_monte_carlo(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                    timeframe: str = "4h", bars: int = 4000, runs: int = 1000):
    """Monte Carlo: bootstrap the trade sequence into an outcome distribution."""
    from services.backtest_lab import monte_carlo
    return monte_carlo(strategy, symbol, timeframe, bars=bars, runs=runs)

@router.get("/lab/out-of-sample")
def lab_out_of_sample(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                      timeframe: str = "4h", bars: int = 4000, split: float = 0.7):
    """Out-of-sample train/test split with an honest overfit verdict."""
    from services.backtest_lab import out_of_sample
    return out_of_sample(strategy, symbol, timeframe, bars=bars, split=split)

@router.get("/lab/sliced")
def lab_sliced(strategy: str = "Decision Brain", timeframe: str = "15m",
               symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT", limit: int = 800):
    """Regime- / session- / symbol-conditional performance for one strategy."""
    from services.backtest_lab import sliced_performance
    syms = tuple(s.strip().upper() for s in symbols.split(",") if s.strip())[:4]
    return sliced_performance(strategy, timeframe, symbols=syms, limit=limit)

@router.get("/scanner/scan")
def scanner_scan(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT", timeframe: str = "4h",
                 bars: int = 300, types: str = ""):
    """Market scanner — rank real setups (breakout / sweep / volume / momentum /
    trend continuation / pullback) across symbols from the cached candles."""
    from services.scanner import scan
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:12]
    tlist = [t.strip() for t in types.split(",") if t.strip()] or None
    return scan(syms, timeframe=timeframe, bars=bars, types=tlist)

@router.get("/marketplace")
def marketplace_catalog():
    """Strategy marketplace — built-in templates + your saved library (with
    favorites, tags, versions)."""
    from services.marketplace import catalog
    return catalog(_wa.custom_store)

@router.post("/marketplace/{sid}/favorite")
def marketplace_favorite(sid: str, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Toggle favorite on a library strategy."""
    _wa._check_secret(x_webhook_secret)
    cur = _wa.custom_store.get(sid)
    if not cur:
        raise _wa.HTTPException(404, "Strategy not found")
    return _wa.custom_store.set_favorite(sid, not cur.get("favorite", False))

@router.post("/marketplace/{sid}/tags")
def marketplace_tags(sid: str, body: _wa.TagsBody, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Set tags on a library strategy."""
    _wa._check_secret(x_webhook_secret)
    r = _wa.custom_store.set_tags(sid, body.tags)
    if r is None:
        raise _wa.HTTPException(404, "Strategy not found")
    return r

@router.post("/marketplace/clone-template")
def marketplace_clone_template(body: _wa.CloneTemplateBody, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Clone a rule-based built-in template into your editable library."""
    _wa._check_secret(x_webhook_secret)
    from services.marketplace import clone_template
    r = clone_template(_wa.custom_store, body.template)
    if "error" in r:
        raise _wa.HTTPException(400, r["error"])
    return r

@router.post("/research/run")
def research_run(body: _wa.ResearchRunBody, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Run an A/B research experiment on real data (train/test + overfit verdict)
    and save it (#15)."""
    _wa._check_secret(x_webhook_secret)
    from services.research import run_research
    rec = run_research(body.name, body.spec_a, body.spec_b, bars=body.bars,
                       label_a=body.label_a, label_b=body.label_b)
    _wa.research_store.save(rec)
    return rec

@router.get("/research")
def research_list():
    """Saved research experiments (summaries)."""
    return {"experiments": _wa.research_store.list()}

@router.get("/research/{rid}/report")
def research_report(rid: str):
    """Markdown report for a saved experiment."""
    from services.research import report_markdown
    rec = _wa.research_store.get(rid)
    if not rec:
        raise _wa.HTTPException(404, "Experiment not found")
    return {"id": rid, "name": rec.get("name"), "report": report_markdown(rec)}

@router.delete("/research/{rid}")
def research_delete(rid: str, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    return {"deleted": _wa.research_store.delete(rid)}

@router.get("/memory/strategy")
def memory_strategy(strategy: str = "Decision Brain", timeframe: str = "15m",
                    symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT", limit: int = 800):
    """Market Memory + Strategy DNA — where this strategy performs best/worst and
    its preferred market / volatility / session / symbols (#12 / #13)."""
    from services.memory import build_memory
    syms = tuple(s.strip().upper() for s in symbols.split(",") if s.strip())[:4]
    return build_memory(strategy, timeframe, symbols=syms, limit=limit)

@router.get("/memory/dna-check")
def memory_dna_check(strategy: str = "Decision Brain", symbol: str = "BTCUSDT",
                     regime: str = "", session: str = "", timeframe: str = "15m"):
    """Does the current context fit the strategy's DNA? (live memory filter)."""
    from services.memory import build_memory, dna_match
    mem = build_memory(strategy, timeframe, symbols=(symbol,) if symbol else ("BTCUSDT",))
    ctx = {"symbol": symbol, "market_regime": regime or None, "session": session or None}
    return {"strategy": strategy, "dna": mem["dna"], "context": ctx, "match": dna_match(mem["dna"], ctx)}

@router.get("/memory/combinations")
def memory_combinations(strategy: str = "Decision Brain", timeframe: str = "15m",
                        symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT", limit: int = 800):
    """Symbol × market-regime win-rate combinations for a strategy (#1)."""
    from services.memory import strategy_combinations
    syms = tuple(s.strip().upper() for s in symbols.split(",") if s.strip())[:4]
    return strategy_combinations(strategy, timeframe, symbols=syms, limit=limit)

@router.post("/memory/snapshot")
def memory_snapshot(strategy: str = "Decision Brain", timeframe: str = "15m",
                    symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT", limit: int = 800,
                    x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Mine a strategy's memory + combinations and PERSIST the snapshot (#1)."""
    _wa._check_secret(x_webhook_secret)
    from services.memory import build_memory, strategy_combinations
    syms = tuple(s.strip().upper() for s in symbols.split(",") if s.strip())[:4]
    mem = build_memory(strategy, timeframe, symbols=syms, limit=limit)
    mem["combinations"] = strategy_combinations(strategy, timeframe, symbols=syms, limit=limit)["combinations"]
    return _wa.memory_store.save(strategy, mem)

@router.get("/memory/snapshots")
def memory_snapshots():
    """Stored memory snapshots + cross-strategy recommendations (#1)."""
    return {"snapshots": _wa.memory_store.list(), "recommendations": _wa.memory_store.recommendations()}

@router.get("/allocation/report")
def allocation_report_endpoint():
    """What the allocator would do right now: per-symbol size tilt from the
    live record + the strategy memory recommends per symbol."""
    from services.allocator import allocation_report
    from services.strategy_presets import SYMBOLS
    return allocation_report(_wa.paper.history(), SYMBOLS, _wa.memory_store)

@router.post("/shadow/start")
def shadow_start(strategy: str = "Decision Brain", conviction: float = 0.0,
                 x_webhook_secret: str = _wa.Header(default="")):
    """Audition a candidate strategy on the live engine's bars with zero
    capital. ``conviction`` overrides the brain's threshold when > 0."""
    _wa._check_secret(x_webhook_secret)
    from services.shadow import ShadowRun
    from services.strategy_presets import make_replay_strategy

    def factory(sym: str):
        strat, err, _sid = make_replay_strategy(strategy, sym, _wa.settings.auto_timeframe)
        if strat is None or err:
            from strategies.brain_strategy import DecisionBrain
            strat = DecisionBrain(sym)
        if conviction > 0 and hasattr(strat, "params"):
            strat.params["conviction_threshold"] = float(conviction)
        return strat

    label = strategy + (f" @conv {conviction}" if conviction > 0 else "")
    _wa.engine.shadow = ShadowRun(label, factory, _wa.engine.symbols)
    _wa.ledger.log(level="info", stage="engine", message=f"Shadow started: {label}")
    return {"started": True, "candidate": label, "symbols": _wa.engine.symbols}

@router.post("/shadow/stop")
def shadow_stop(x_webhook_secret: str = _wa.Header(default="")):
    _wa._check_secret(x_webhook_secret)
    was = _wa.engine.shadow.name if _wa.engine.shadow else None
    _wa.engine.shadow = None
    return {"stopped": was is not None, "candidate": was}

@router.get("/shadow/report")
def shadow_report():
    """Candidate vs incumbent on the same live candles, with a promotion
    verdict once both sides have 20+ closed trades."""
    from services.shadow import live_stats_from_history
    if _wa.engine.shadow is None:
        return {"active": False,
                "note": "No shadow running. POST /shadow/start to audition a candidate."}
    live = live_stats_from_history(_wa.paper.history(), since_iso=_wa.engine.shadow.started_at)
    return {"active": True, **_wa.engine.shadow.report(live)}

def _closed_paper_trades() -> int:
    try:
        return sum(1 for t in _wa.paper.history() if t.get("pnl") is not None)
    except Exception:  # noqa: BLE001
        return 0


@router.get("/retune/gate")
def research_retune_gate():
    """Strategy retune gate — may a retune run given the live paper sample size?
    Below 30 closed trades the answer is no (except a critical-bug override);
    50+ is evidence level. Never touches live trading."""
    from services.retune_gate import evaluate_retune_gate
    return evaluate_retune_gate(closed_paper_trades=_closed_paper_trades())


@router.post("/retune/run")
def research_retune(timeframe: str = "", critical_bug: bool = False,
                    x_webhook_secret: str = _wa.Header(default="")):
    """Run the self-retune search now: grid over brain configs on REAL data
    (train/test split); if a candidate beats the incumbent on unseen data it
    auto-starts as a shadow. Promotion stays manual.

    Gated by the live paper sample size (Phase 10): below 30 closed trades this
    refuses to run unless ``critical_bug=true`` (logged), so the strategy is
    never retuned from a small sample."""
    _wa._check_secret(x_webhook_secret)
    from services.retune_gate import evaluate_retune_gate
    gate = evaluate_retune_gate(closed_paper_trades=_closed_paper_trades(),
                                critical_bug=critical_bug)
    if not gate["allowed"]:
        _wa.ledger.log(level="info", stage="research",
                       message=f"Retune blocked by gate: {gate['stage']} — {gate['reason']}")
        return {"ran": False, "blocked": True, "gate": gate}
    if critical_bug:
        _wa.ledger.log(level="warning", stage="research",
                       message="Retune ran under CRITICAL-BUG override (sample gate bypassed).")
    from services.retune import retune
    res = retune(_wa.engine, _wa.notifier.dispatch,
                 timeframe=timeframe or _wa.engine.timeframe, force=True)
    _wa._last_retune = res
    _wa.ledger.log(level="info", stage="research",
               message=f"Manual retune: {res.get('verdict', '-')}")
    return {"ran": True, "blocked": False, "gate": gate, **res}

@router.get("/retune/report")
def research_retune_report():
    """The last retune run (manual or nightly auto-check)."""
    return _wa._last_retune or {"ran": False, "note": "No retune has run yet. "
                            "POST /retune/run to search now."}

@router.post("/research/validate-context")
def research_validate_context(timeframe: str = "1h", bars: int = 2500,
                              x_webhook_secret: str = _wa.Header(default="")):
    """Validate the three context modifiers (cross-asset gate, funding sizing,
    sentiment sizing) on REAL cached candles + real funding / Fear&Greed
    history. Per-modifier verdicts; nothing is enabled automatically."""
    _wa._check_secret(x_webhook_secret)
    from services.context_brain import validate_context
    rep = validate_context(timeframe=timeframe, bars=max(600, min(bars, 6000)))
    _wa.ledger.log(level="info", stage="research",
               message=("Context validation: cross=%s funding=%s sentiment=%s" % (
                   rep["cross_asset"].get("verdict"), rep["funding"].get("verdict"),
                   rep["sentiment"].get("verdict"))))
    return rep

@router.get("/counterfactual/report")
def counterfactual_report():
    """Every gate graded by what it actually blocked: saved_r per rule
    (positive = the rule blocks losers), the vetoed trades still resolving,
    and which rules the evidence has falsified."""
    return _wa.counterfactual.report()

@router.get("/learning/report")
def learning_report():
    """What the bot has learned from its own trades: named repeated mistakes
    with evidence, the bounded corrections currently in force, and the full
    applied/relaxed evolution timeline."""
    return _wa.learning_book.report()

@router.post("/learning/run")
def learning_run(x_webhook_secret: str = _wa.Header(default="")):
    """Force a re-learn from the full trade history right now."""
    _wa._check_secret(x_webhook_secret)
    return _wa.learning_book.update(_wa.paper.history(), _wa.pipeline.alert_context())

@router.get("/strategy/league")
def strategy_league(symbols: str = "BTCUSDT,ETHUSDT", timeframe: str = "1h",
                    bars: int = 2500):
    """Every built-in strategy on the SAME real candles: ranked by expectancy
    (win rate shown but not trusted alone), with the pairwise correlation of
    their daily return streams — which pairs diversify vs duplicate."""
    from services.strategy_league import league
    from services.ttl_cache import cached
    syms = tuple(t.strip() for t in symbols.split(",") if t.strip())
    n = max(600, min(bars, 6000))
    return cached(f"league:{','.join(syms)}:{timeframe}:{n}", 300,
                  lambda: league(symbols=syms, timeframe=timeframe, bars=n))

@router.get("/news/world")
def news_world():
    """World & market news from public RSS (no keys): crypto + stocks + macro
    outlets, each headline tagged with the markets it touches, plus a REAL
    daily-move snapshot (BTC / S&P 500 / Nasdaq / Gold) for impact context."""
    from services.news import cached_world_news
    return cached_world_news()

@router.get("/market/funding")
def market_funding(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT"):
    """Live perp funding rates with interpretation (crowded side / squeeze
    risk). Spot-only or offline -> available: false, never fabricated."""
    from services.funding import funding_rates
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    return funding_rates(syms)

@router.get("/marketplace/rank")
def marketplace_rank(symbol: str = "BTCUSDT", timeframe: str = "15m",
                     strategies: str = "Decision Brain,Trend Following,Supply/Demand,EMA 20/50",
                     limit: int = 600):
    """Performance ranking — net R per strategy on real data (which strategy
    performs best for this symbol/timeframe)."""
    from services.replay import build_replay
    from services.ttl_cache import cached
    strats = [s.strip() for s in strategies.split(",") if s.strip()][:6]

    def _rank() -> dict:
        rows = []
        for st in strats:
            rep = build_replay(symbol, timeframe, limit, strategy=st)
            stt = rep["stats"]
            rows.append({"strategy": st, "trades": stt["trades"], "win_rate": stt["win_rate"],
                         "profit_factor": stt["profit_factor"], "net_r": stt["net_r"]})
        rows.sort(key=lambda r: r["net_r"], reverse=True)
        return {"symbol": symbol, "timeframe": timeframe, "ranking": rows,
                "best": rows[0] if rows else None}

    return cached(f"rank:{symbol}:{timeframe}:{limit}:{','.join(strats)}", 300, _rank)

@router.get("/markets/watchlist")
def markets_watchlist(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT", timeframe: str = "1d"):
    """Real watchlist quotes from the cached Binance candles — last price, period
    change, volatility and a mini sparkline. Honest 'unavailable' per symbol when
    no real history is cached (never a faked price)."""
    from data.market_data import get_bars
    from services.risk_engine import log_returns, _stdev
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:12]
    out = []
    for sym in syms:
        rows, src = get_bars(sym, n=60, timeframe=timeframe, require_real=True)
        if not rows or len(rows) < 2:
            out.append({"symbol": sym, "available": False, "source": src})
            continue
        closes = [b.close for b in rows]
        last, prev = closes[-1], closes[-2]
        vol = _stdev(log_returns(closes)) * 100
        out.append({
            "symbol": sym, "available": True, "source": src,
            "last": round(last, 6), "change_pct": round((last / prev - 1) * 100, 2),
            "vol_pct": round(vol, 2), "spark": [round(c, 6) for c in closes[-30:]],
            "bars": len(rows),
        })
    return {"timeframe": timeframe, "symbols": out}

@router.post("/strategy/custom/simulate")
def custom_simulate(body: _wa.SimRequest):
    """Run a user-built strategy spec over REAL historical data (simulation only).

    The TradeBrain quality filter is ON by default so weak setups are blocked
    and reported. Pass ``spec["quality_filter"] = false`` to see raw, unfiltered
    results, or set ``spec["min_score"]`` to tune the threshold (default 60).
    """
    from strategies.custom import simulate, validate, describe, _stop_distance
    from strategies.brain import TradeBrain
    from strategies.diagnosis import diagnose
    from data.market_data import get_bars
    spec = body.spec
    symbol = spec.get("symbol", "BTCUSDT")
    timeframe = spec.get("timeframe", "4h")
    n = max(300, min(int(body.bars or 3000), 10000))
    rows, source = get_bars(symbol, n=n, timeframe=timeframe)

    use_brain = spec.get("quality_filter", True)
    min_score = int(spec.get("min_score", 60))
    brain = TradeBrain() if use_brain else None
    # Default to safer exits (break-even after +1R) unless the spec overrides.
    if use_brain and "exit" not in spec:
        spec = {**spec, "exit": {"breakeven_at_r": 1.0}}
    results = simulate(spec, rows, brain=brain, min_score=min_score if use_brain else 0)
    results["diagnosis"] = diagnose(results, results.get("blocked"))

    # Pre-trade position-sizing calculation on the latest bar (real numbers).
    equity = _wa.settings.starting_cash
    risk_pct = float(spec.get("risk_per_trade_pct", 0.01))
    entry = rows[-1].close
    stop_dist = _stop_distance(spec.get("stop") or {}, entry, rows, len(rows) - 1)
    risk_dollars = equity * risk_pct
    size = (risk_dollars / stop_dist) if stop_dist > 0 else 0.0
    notional = size * entry
    sizing = {
        "model": "percent_risk", "equity": equity, "risk_pct": risk_pct,
        "entry": round(entry, 6), "stop_distance": round(stop_dist, 6),
        "risk_dollars": round(risk_dollars, 2), "position_size": round(size, 6),
        "notional": round(notional, 2), "leverage_x": round(notional / equity, 2) if equity else 0,
    }
    return {
        "results": results,
        "warnings": validate(spec, results),
        "description": describe(spec),
        "sizing": sizing,
        "data_source": source,
        "symbol": symbol, "timeframe": timeframe,
        "label": "Simulation Result",
        "brain": {"quality_filter": bool(use_brain), "min_score": min_score,
                  "blocked_count": results.get("blocked_count", 0)},
    }

@router.post("/strategy/custom/optimize")
def custom_optimize(body: _wa.SimRequest):
    """Train/test optimisation. Honest: flags results overfit unless the unseen
    validation period also improves. Optimises min score / RR / ATR stop only."""
    from strategies.optimize import walk_forward
    from data.market_data import get_bars
    spec = body.spec
    symbol = spec.get("symbol", "BTCUSDT")
    timeframe = spec.get("timeframe", "4h")
    n = max(600, min(int(body.bars or 4000), 10000))
    rows, source = get_bars(symbol, n=n, timeframe=timeframe)
    report = walk_forward(spec, rows)
    report["data_source"] = source
    report["symbol"] = symbol
    report["timeframe"] = timeframe
    return report

@router.get("/control/options")
def control_options():
    """Strategy / symbol / timeframe / mode options + default brain tuning for
    the top control bar."""
    from services.strategy_presets import STRATEGY_OPTIONS, SYMBOLS, TIMEFRAMES, MODES, DEFAULT_TUNING
    return {"strategies": STRATEGY_OPTIONS, "symbols": SYMBOLS, "timeframes": TIMEFRAMES,
            "modes": MODES, "default_tuning": DEFAULT_TUNING}

@router.post("/control/simulate")
def control_simulate(body: _wa.ControlSimRequest):
    """Rerun a REAL simulation for the chosen strategy/symbol/timeframe/tuning.
    The macro/confirmation timeframes drive the multi-timeframe gate."""
    from services.strategy_presets import run_simulation
    return run_simulation(body.strategy, body.symbol, body.timeframe,
                          tuning=body.tuning, custom_spec=body.custom_spec, bars=body.bars,
                          macro=body.macro, confirmation=body.confirmation, realistic=body.realistic)

@router.post("/control/auto-tune")
def control_auto_tune(body: _wa.ControlSimRequest):
    """Search the brain-tuning space on real data (train/test split) and return
    the best configuration with an honest overfit verdict."""
    from services.strategy_presets import auto_tune
    return auto_tune(body.strategy, body.symbol, body.timeframe, macro=body.macro,
                     confirmation=body.confirmation, custom_spec=body.custom_spec, bars=body.bars)

@router.post("/control/compare")
def control_compare(body: _wa.ControlCompareRequest):
    """Compare two strategy/timeframe/symbol configurations on the same real data."""
    from services.strategy_presets import compare
    return compare(body.a, body.b, bars=body.bars)

@router.post("/control/save-version")
def control_save_version(body: _wa.ControlSimRequest, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Snapshot the current control-bar configuration as a new strategy version
    (never overwrites older versions)."""
    _wa._check_secret(x_webhook_secret)
    from services.strategy_presets import run_simulation
    sim = run_simulation(body.strategy, body.symbol, body.timeframe,
                         tuning=body.tuning, custom_spec=body.custom_spec, bars=body.bars)
    if not sim.get("available"):
        raise _wa.HTTPException(400, sim.get("error", "Cannot version without real data."))
    r = sim["results"]
    stats = {k: r[k] for k in ("total_trades", "win_rate", "profit_factor", "net_r",
                               "max_drawdown_pct", "expectancy_r") if k in r}
    params = {"strategy": body.strategy, "symbol": body.symbol, "timeframe": body.timeframe,
              "tuning": body.tuning, "spec": sim.get("spec")}
    return _wa.version_store.add_version(body.strategy, params, stats,
                                     note=f"{body.strategy} {body.symbol} {body.timeframe}")

@router.get("/mtf/analyze")
def mtf_analyze(symbol: str = "BTCUSDT"):
    """Multi-timeframe decision: analyse Weekly→Daily→4H→15M→5M together and
    explain whether a trade is allowed, blocked or still waiting."""
    from services.mtf_engine import analyze
    return analyze(symbol)

@router.post("/research/validate-real")
def research_validate_real(strategy: str = "Decision Brain", timeframe: str = "4h",
                           bars: int = 4000,
                           x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """The honest gauntlet: integrity + walk-forward out-of-sample + realistic
    fills, per symbol, on REAL cached candles. Says plainly if the edge holds."""
    _wa._check_secret(x_webhook_secret)
    from services.validation import validate_real
    rep = validate_real(strategy, timeframe=timeframe, bars=bars)
    _wa.ledger.log(level="info", stage="research",
               message=f"Real-data validation: {strategy} {timeframe} -> {rep['overall']}")
    return rep

@router.get("/performance/track-record")
def performance_track_record(strategy: str = "Decision Brain", symbol: str = "BTCUSDT",
                             timeframe: str = "4h"):
    """Live paper record vs the backtest promise for the same config — the
    bridge between backtest and real money."""
    from services.track_record import track_record
    return track_record(_wa.paper.history(), strategy=strategy, symbol=symbol,
                        timeframe=timeframe)

@router.get("/replay/run")
def replay_run(symbol: str = "BTCUSDT", timeframe: str = "15m", limit: int = 800,
               start: _wa.Optional[str] = None, end: _wa.Optional[str] = None,
               strategy: str = "Supply/Demand", source: str = "binance",
               macro: _wa.Optional[str] = None, confirmation: _wa.Optional[str] = None,
               memory_filter: bool = False, realistic: bool = False):
    """Precompute a no-lookahead decision timeline for TradingView-style replay
    using the SELECTED strategy. ``source`` = binance | demo. ``start``/``end``
    (YYYY-MM-DD) jump to a specific historical window. ``macro``/``confirmation``
    pick the higher timeframes that drive the multi-timeframe entry gate.
    ``memory_filter`` makes the engine skip the strategy's historically-weak
    regimes, learned from its saved memory snapshot (#1/#13)."""
    from services.replay import build_replay
    avoid = None
    if memory_filter:
        from services.memory import avoid_regimes_from_combinations
        snap = _wa.memory_store.get(strategy)
        if snap and snap.get("combinations"):
            avoid = avoid_regimes_from_combinations(snap["combinations"])
    fill_cost = 0.0
    if realistic:
        from services.fill_model import RealisticFill
        fill_cost = RealisticFill().cost_pct
    rep = build_replay(symbol, timeframe, limit, start=start, end=end,
                       strategy=strategy, source=source,
                       macro=macro, confirmation=confirmation, avoid_regimes=avoid,
                       fill_cost_pct=fill_cost)
    if rep.get("meta", {}).get("debug") is not None:
        rep["meta"]["debug"]["memory_filter"] = avoid or []
        rep["meta"]["debug"]["fills"] = "realistic" if realistic else "ideal"
    return rep

@router.get("/strategies/registry")
def strategies_registry():
    """The real strategy registry the selectors pull from (id / version / meta)."""
    from services.strategy_presets import REGISTRY
    return {"strategies": REGISTRY}

@router.get("/replay/stats")
def replay_stats(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT",
                 timeframe: str = "15m", limit: int = 600):
    """Per-asset replay stats (BTC/ETH/SOL/XRP) for the statistics panel."""
    from services.replay import multi_asset_stats
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:6]
    return {"timeframe": timeframe, "assets": multi_asset_stats(syms, timeframe, limit)}

@router.get("/evolution/sentiment")
def evolution_sentiment():
    """Real-world market sentiment (Fear & Greed, dominance) — filter only."""
    from services.sentiment import market_sentiment
    return market_sentiment()

@router.post("/evolution/learn")
def evolution_learn(symbol: str = "BTCUSDT", timeframe: str = "15m", limit: int = 1000,
                    strategy: str = "Supply/Demand",
                    x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Study real replay results for a symbol, derive evidence-based lessons +
    upgrade suggestions, and record them (status 'Suggested' — never auto-applied)."""
    _wa._check_secret(x_webhook_secret)
    from services.replay import build_replay
    from services.lessons import lessons_from_results, mtf_disagreement_lessons
    from services.evolution import suggest_improvements
    rep = build_replay(symbol, timeframe, limit, strategy=strategy)
    if rep["meta"]["bars"] == 0:
        return {"studied_trades": 0, "lessons": [], "upgrades": [],
                "error": ("No real candles cached for this symbol/timeframe — press "
                          "'Load real Binance data' in the Bot Control Center first, "
                          "then Study & Learn.")}
    bundle = {"trades": rep["trades"], "stats": rep["stats"], "diagnosis": _wa._replay_diag(rep)}
    # timeframe-disagreement detector (evidence-based, from the per-bar trends)
    dis = mtf_disagreement_lessons(rep, symbol=symbol, strategy=strategy)
    lessons = lessons_from_results(bundle, symbol=symbol, strategy=strategy) + dis
    added_lessons = _wa.lesson_store.add_many(lessons)
    added_upgrades = _wa.upgrade_store.add_many(
        suggest_improvements(bundle, symbol=symbol, strategy=strategy, extra_lessons=dis))
    _wa.ledger.log(level="info", stage="evolution",
               message=f"Learned from {symbol}: {len(added_lessons)} new lessons, "
                       f"{len(added_upgrades)} new suggestions")
    return {"lessons": added_lessons, "upgrades": added_upgrades,
            "studied_trades": rep["stats"]["trades"], "data_source": rep["meta"]["data_source"]}

@router.get("/evolution/lessons")
def evolution_lessons():
    return {"lessons": _wa.lesson_store.list(), "weekly": _wa.lesson_store.weekly_count(),
            "status_counts": _wa.lesson_store.status_counts()}

@router.post("/evolution/lessons/{lid}/status")
def evolution_lesson_status(lid: str, status: str,
                            x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    res = _wa.lesson_store.set_status(lid, status)
    if res is None:
        raise _wa.HTTPException(404, "Lesson not found or invalid status")
    return res

@router.get("/evolution/upgrades")
def evolution_upgrades():
    return {"upgrades": _wa.upgrade_store.list_sorted(), "status_counts": _wa.upgrade_store.status_counts()}

@router.post("/evolution/upgrades/{uid}/status")
def evolution_upgrade_status(uid: str, status: str,
                             x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Advance an upgrade through its lifecycle. Approve/Reject/Archive are
    human-only; the bot can never set them itself."""
    _wa._check_secret(x_webhook_secret)
    res = _wa.upgrade_store.set_status(uid, status, by="human")
    if res is None:
        raise _wa.HTTPException(404, "Upgrade not found")
    if "error" in res:
        raise _wa.HTTPException(400, res["error"])
    _wa.ledger.log(level="info", stage="evolution", message=f"Upgrade {uid[:8]} -> {status} (human)")
    return res

@router.post("/evolution/experiment")
def evolution_experiment(body: _wa.ExperimentRequest):
    """A/B two strategy specs with a train/test split + overfitting verdict."""
    from services.evolution import run_experiment
    return run_experiment(body.base, body.variant, bars=body.bars)

@router.post("/evolution/versions")
def evolution_add_version(body: dict, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Snapshot a strategy spec as a new version (with its simulated stats)."""
    _wa._check_secret(x_webhook_secret)
    from strategies.custom import simulate
    from strategies.brain import TradeBrain
    from data.market_data import get_bars
    spec = body.get("spec") or {}
    strategy = body.get("strategy") or spec.get("name", "Strategy")
    rows, _ = get_bars(spec.get("symbol", "BTCUSDT"), n=4000, timeframe=spec.get("timeframe", "4h"))
    r = simulate(spec, rows, brain=TradeBrain(), min_score=int(spec.get("min_score", 60)))
    stats = {k: r[k] for k in ("total_trades", "win_rate", "profit_factor", "net_r",
                               "max_drawdown_pct", "avg_rr", "expectancy_r") if k in r}
    return _wa.version_store.add_version(strategy, spec, stats, note=body.get("note", ""))

@router.get("/evolution/versions")
def evolution_versions(strategy: str):
    return _wa.version_store.compare(strategy)

@router.post("/evolution/upgrades/{uid}/promote")
def evolution_promote(uid: str, body: dict = None,
                      x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Turn an APPROVED, auto-applicable upgrade into a new strategy version and
    run its backtest. The version then flows through Sim -> Paper -> (locked) Live."""
    _wa._check_secret(x_webhook_secret)
    body = body or {}
    up = next((u for u in _wa.upgrade_store.list_sorted() if u["id"] == uid), None)
    if up is None:
        raise _wa.HTTPException(404, "Upgrade not found")
    if up.get("status") != "Approved":
        raise _wa.HTTPException(400, "Approve the upgrade before promoting it to a version.")
    patch = up.get("apply")
    if not patch:
        raise _wa.HTTPException(400, "This upgrade needs a manual change — no auto-patch available.")

    from services.evolution import apply_patch
    from strategies.custom import simulate
    from strategies.brain import TradeBrain
    from data.market_data import get_bars

    strategy = up.get("strategy", "Strategy")
    prior = _wa.version_store.versions(strategy)
    base = body.get("base_spec") or (prior[-1]["params"] if prior else _wa._default_base_spec(strategy, up.get("symbol", "BTCUSDT")))
    new_spec = apply_patch(base, patch)

    rows, _ = get_bars(new_spec.get("symbol", "BTCUSDT"), n=4000, timeframe=new_spec.get("timeframe", "4h"))
    r = simulate(new_spec, rows, brain=TradeBrain(), min_score=int(new_spec.get("min_score", 60)))
    stats = {k: r[k] for k in ("total_trades", "win_rate", "profit_factor", "net_r",
                               "max_drawdown_pct", "expectancy_r") if k in r}
    version = _wa.version_store.add_version(strategy, new_spec, stats, note=up["title"])  # backtest gate done
    _wa.upgrade_store.set_status(uid, "Backtested", by="human")
    _wa.ledger.log(level="info", stage="evolution",
               message=f"Promoted upgrade {uid[:8]} -> {version['label']} (backtest done; sim/paper pending)")
    return {"version": version, "applied_patch": patch}

@router.post("/evolution/versions/{vid}/advance")
def evolution_advance_version(vid: str, gate: str,
                              x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Advance a version through the safety gates. 'simulation' runs a sim;
    'paper' is a human-confirmed checkpoint; 'live_unlock' stays locked with no
    broker connected (by design)."""
    _wa._check_secret(x_webhook_secret)
    v = _wa.version_store.get(vid)
    if v is None:
        raise _wa.HTTPException(404, "Version not found")
    stats = None
    if gate == "simulation":
        from strategies.custom import simulate
        from strategies.brain import TradeBrain
        from data.market_data import get_bars
        spec = v["params"]
        rows, _ = get_bars(spec.get("symbol", "BTCUSDT"), n=3000, timeframe=spec.get("timeframe", "4h"))
        r = simulate(spec, rows, brain=TradeBrain(), min_score=int(spec.get("min_score", 60)))
        stats = {k: r[k] for k in ("total_trades", "win_rate", "profit_factor", "net_r", "expectancy_r") if k in r}
    res = _wa.version_store.advance_gate(vid, gate, stats=stats,
                                     broker_connected=bool(getattr(_wa.engine, "live", False) and False))
    if res is None:
        raise _wa.HTTPException(404, "Version not found")
    if "error" in res:
        # live stays locked: surface the reason, not a hard failure
        if gate == "live_unlock":
            return res
        raise _wa.HTTPException(400, res["error"])
    _wa.ledger.log(level="info", stage="evolution", message=f"{v['label']} gate '{gate}' advanced")
    return res

@router.get("/evolution/market-context")
def evolution_market_context():
    """Live real-world market widgets (Fear & Greed, dominance, ETH/BTC, funding,
    OI, news…). Key-gated sources show 'Not connected' — never fake data."""
    from services.market_context import market_context
    return market_context(_wa.provider_settings)

@router.get("/evolution/providers")
def evolution_providers():
    """Per-provider connection status for the Data Providers settings panel
    (never exposes the key values)."""
    return {"providers": _wa.provider_settings.status()}

@router.post("/evolution/providers")
def evolution_set_providers(body: dict, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Save provider API keys (local store). Blanks are ignored (won't wipe)."""
    _wa._check_secret(x_webhook_secret)
    return {"providers": _wa.provider_settings.save(body or {})}

@router.get("/evolution/dashboard")
def evolution_dashboard():
    """Aggregate widgets for the Evolution dashboard."""
    from services.sentiment import market_sentiment
    sent = market_sentiment()
    return {
        "sentiment": {"available": sent.get("available"), "mood": sent.get("mood"),
                      "risk_mode": sent.get("risk_mode"), "fear_greed": sent.get("fear_greed")},
        "lessons_weekly": _wa.lesson_store.weekly_count(),
        "lessons_total": len(_wa.lesson_store.list()),
        "lesson_status": _wa.lesson_store.status_counts(),
        "upgrade_status": _wa.upgrade_store.status_counts(),
        "workflow": ["Observe", "Diagnose", "Suggest", "New version", "Backtest",
                     "Simulation", "Paper trading", "Human approval", "Live unlock"],
        "live_rule": "Live trading changes require human approval — the bot never auto-applies upgrades.",
    }

@router.get("/strategy/builtin/simulate")
def builtin_simulate(strategy: str = "smc", symbol: str = "BTCUSDT",
                     timeframe: str = "4h", bars: int = 3000):
    """Simulate a built-in strategy (e.g. SMC) over real historical bars and
    return the same rich shape as the custom simulator (metrics + diagnosis)."""
    from strategies.custom import simulate_strategy
    from strategies.diagnosis import diagnose
    from data.market_data import get_bars
    n = max(300, min(int(bars or 3000), 10000))
    rows, source = get_bars(symbol, n=n, timeframe=timeframe)
    strat = _wa._build_builtin(strategy, symbol)
    results = simulate_strategy(strat, rows)
    results["diagnosis"] = diagnose(results, [])
    label = next((s["label"] for s in _wa._STRATEGY_CATALOG if s["key"] == strategy), strategy)
    return {
        "results": results,
        "warnings": [],
        "description": f"Built-in strategy: {label}.",
        "data_source": source, "symbol": symbol, "timeframe": timeframe,
        "label": "Simulation Result",
        "brain": {"quality_filter": False, "min_score": 0, "blocked_count": 0},
    }

@router.get("/strategy/blocks")
def strategy_blocks():
    """The no-code builder's block palette — every block maps 1:1 to the spec
    engine, so the UI stays data-driven and can't invent behaviour."""
    from services.strategy_builder import block_catalog
    return block_catalog()


@router.get("/strategy/templates")
def strategy_templates():
    """Ready-made strategy templates (SMC, ICT, EMA trend, breakout, …)."""
    from services.strategy_builder import templates
    return {"templates": templates()}


@router.post("/strategy/ai-review")
def strategy_ai_review(body: dict):
    """AI review of a strategy spec: complexity, risk, strengths, weaknesses,
    improvements and an estimated confidence. Runs a quick real-data backtest so
    the confidence is grounded, not invented."""
    from services.strategy_builder import ai_review
    from strategies.custom import simulate
    from strategies.brain import TradeBrain
    from data.market_data import get_bars
    spec = body.get("spec") or body
    results = None
    try:
        symbol = spec.get("symbol", "BTCUSDT")
        timeframe = spec.get("timeframe", "4h")
        rows, _ = get_bars(symbol, n=int(body.get("bars", 2000)), timeframe=timeframe)
        if rows:
            results = simulate(spec, rows, brain=TradeBrain() if spec.get("quality_filter", True) else None,
                               min_score=int(spec.get("min_score", 60)) if spec.get("quality_filter", True) else 0)
    except Exception:  # noqa: BLE001 — review still works without a backtest
        results = None
    return ai_review(spec, results)


@router.get("/strategy/custom")
def custom_list():
    return _wa.custom_store.list()

@router.post("/strategy/custom")
def custom_save(spec: dict, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    saved = _wa.custom_store.save(spec)
    _wa.ledger.log(level="info", stage="audit", message=f"Custom strategy saved: {saved.get('name', saved['id'])}")
    return saved

@router.delete("/strategy/custom/{sid}")
def custom_delete(sid: str, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    ok = _wa.custom_store.delete(sid)
    if ok:
        _wa.ledger.log(level="info", stage="audit", message=f"Custom strategy deleted: {sid}")
    return {"deleted": ok}

@router.post("/strategy/custom/{sid}/duplicate")
def custom_duplicate(sid: str, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    dup = _wa.custom_store.duplicate(sid)
    if dup is None:
        raise _wa.HTTPException(404, "Strategy not found")
    return dup

@router.get("/strategy/custom/{sid}/history")
def custom_history(sid: str):
    """Version snapshots for a strategy (oldest first). Each save that changes the
    definition pushes the previous state here — the strategy's audit trail."""
    versions = _wa.custom_store.history(sid)
    if versions is None:
        raise _wa.HTTPException(404, "Strategy not found")
    return {"id": sid, "versions": versions}

@router.post("/strategy/custom/{sid}/restore")
def custom_restore(sid: str, body: dict, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Roll a strategy back to a prior version. The current state is snapshotted
    first, so the restore itself is undoable."""
    _wa._check_secret(x_webhook_secret)
    r = _wa.custom_store.restore(sid, int(body.get("v", -1)))
    if r is None:
        raise _wa.HTTPException(404, "Strategy or version not found")
    _wa.ledger.log(level="info", stage="audit",
                   message=f"Custom strategy restored to v{body.get('v')}: {r.get('name', sid)}")
    return r

@router.post("/strategy/custom/{sid}/favorite")
def custom_favorite(sid: str, body: dict, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    r = _wa.custom_store.set_favorite(sid, bool(body.get("on", True)))
    if r is None:
        raise _wa.HTTPException(404, "Strategy not found")
    return r

@router.post("/strategy/custom/{sid}/meta")
def custom_meta(sid: str, body: dict, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Rename and/or move a saved strategy into a folder (library organisation)."""
    _wa._check_secret(x_webhook_secret)
    r = _wa.custom_store.set_meta(sid, name=body.get("name"), folder=body.get("folder"))
    if r is None:
        raise _wa.HTTPException(404, "Strategy not found")
    return r

@router.post("/strategy/custom/{sid}/deploy")
def custom_deploy(sid: str, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Deploy a saved custom strategy to PAPER trading (never live)."""
    _wa._check_secret(x_webhook_secret)
    spec = _wa.custom_store.get(sid)
    if not spec:
        raise _wa.HTTPException(404, "Strategy not found")
    from strategies.custom_adapter import CustomStrategyAdapter
    name = spec.get("name", "Strategy")

    def _log_block(info: dict):
        """Record a brain-blocked paper setup to the decision log (avoiding bad
        trades is part of the edge — make it visible)."""
        _wa.ledger.log(level="info", stage="brain",
                   message=(f"{info['symbol']} {info['side']} blocked — {info['reason']} "
                            f"(score {info['score']}, {info['regime']}, HTF {info['htf_bias']})"),
                   symbol=info["symbol"])

    _wa.engine.reconfigure(
        symbols=[spec.get("symbol", "BTCUSDT")],
        timeframe=spec.get("timeframe", "4h"),
        strategy_factory=lambda sym, _s=spec: CustomStrategyAdapter(sym, _s, on_block=_log_block),
        label=f"Custom: {name}",
    )
    _wa.ledger.log(level="info", stage="engine", message=f"Deployed custom strategy '{name}' to paper trading")
    _wa.ledger.add_alert(severity="info", category="system", title="Custom strategy deployed",
                     detail=f"{name} — paper mode (simulation only, no live broker)")
    return {"deployed": True, "status": _wa.engine.status()}

@router.get("/strategy/compare")
def strategy_compare(symbol: str = "BTCUSDT", timeframe: str = "4h",
                     strategy: str = "brain", bars: int = 3000):
    """Backtest a pre-built strategy on the same data, to compare vs a custom one."""
    from data.market_data import get_bars
    from backtest import run as _run, _metrics
    rows, source = get_bars(symbol, n=max(300, min(int(bars), 10000)), timeframe=timeframe)
    m = _metrics(_run(rows, strategy=strategy))
    return {
        "strategy": strategy, "data_source": source, "symbol": symbol, "timeframe": timeframe,
        "metrics": {
            "total_trades": m.trades, "win_rate": round(m.win_rate, 1),
            "profit_factor": round(m.profit_factor, 2), "net_r": round(m.net_r, 2),
            "max_drawdown_r": round(m.max_dd_r, 1), "avg_r": round(m.avg_r, 3),
        },
    }

@router.post("/market/symbols")
def set_symbols(body: _wa.SymbolsUpdate, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Set the engine's traded symbols (the active watchlist) and restart it."""
    _wa._check_secret(x_webhook_secret)
    syms = [s.strip().upper() for s in body.symbols if s.strip()]
    if not syms:
        raise _wa.HTTPException(400, "At least one symbol is required")
    _wa.engine.reconfigure(symbols=syms, timeframe=_wa.engine.timeframe,
                       strategy_factory=_wa.engine.strategy_factory, label=_wa.engine.strategy_label)
    # persist so the watchlist survives a server restart/redeploy
    _wa.save_overrides(_wa.settings.settings_path, _wa._settings_snapshot())
    _wa.ledger.log(level="info", stage="audit", message=f"Watchlist applied: {', '.join(syms)}")
    return {"applied": True, "symbols": _wa.engine.symbols}

@router.get("/strategy/list")
def strategy_list():
    """Real list of selectable engine strategies + which one is active."""
    return {"active": _wa.settings.auto_strategy, "timeframe": _wa.engine.timeframe,
            "strategies": _wa._STRATEGY_CATALOG}

@router.post("/strategy/select")
def strategy_select(body: _wa.StrategySelect, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Switch the live (paper) engine's active built-in strategy and persist it.

    This actually changes the backend logic: the engine is reconfigured with the
    selected strategy factory so every symbol now trades the chosen strategy. The
    choice is saved so it survives a restart. Live trading stays locked (paper)."""
    _wa._check_secret(x_webhook_secret)
    key = (body.strategy or "").strip()
    entry = next((s for s in _wa._STRATEGY_CATALOG if s["key"] == key or s["label"] == key), None)
    if not entry:
        raise _wa.HTTPException(400, f"Unknown strategy '{key}'. "
                                 f"Choose one of: {', '.join(s['key'] for s in _STRATEGY_CATALOG)}.")
    if entry["key"] == _wa.settings.auto_strategy:
        return {"applied": True, "active": _wa.settings.auto_strategy, "unchanged": True,
                "status": _wa.engine.status()}
    _wa.settings.auto_strategy = entry["key"]                 # _make_strategy reads this live
    if _wa.engine.running:                                    # swap on the running engine
        _wa.engine.reconfigure(symbols=_wa.engine.symbols, timeframe=_wa.engine.timeframe,
                           strategy_factory=_wa._make_strategy, label=entry["label"])
    else:                                                 # respect a stopped engine
        _wa.engine.strategy_factory = _wa._make_strategy
        _wa.engine.strategy_label = entry["label"]
    _wa.save_overrides(_wa.settings.settings_path, _wa._settings_snapshot())
    _wa.ledger.log(level="info", stage="audit",
               message=f"Active strategy switched to {entry['label']} ({entry['key']})")
    _wa.ledger.add_alert(severity="info", category="system", title="Strategy switched",
                     detail=f"Engine now trading {entry['label']} (paper mode)")
    return {"applied": True, "active": _wa.settings.auto_strategy,
            "label": entry["label"], "status": _wa.engine.status()}

@router.get("/strategy/performance")
def strategy_performance():
    """The bot's live paper-trading track record (real executed trades)."""
    from services.performance import summarize
    stats = summarize(_wa.paper.history(), _wa.paper.starting_balance)
    stats["strategy"] = _wa.engine.strategy_label
    stats["mode"] = "live" if _wa.engine.live else "replay"
    return stats

@router.get("/strategy/health")
def strategy_health():
    """Strategy health (rolling deterioration check) + the brain's block rate:
    how many setups the quality filter took vs avoided in paper."""
    from services.strategy_health import StrategyHealthMonitor
    hist = [{**t, "r": (t.get("rr") if t.get("rr") is not None else 0.0)} for t in _wa.paper.history()]
    health = StrategyHealthMonitor().evaluate(hist)

    logs = _wa.ledger.get_logs(limit=1000)
    blocked = sum(1 for l in logs if l.get("stage") == "brain")
    taken = sum(1 for l in logs if l.get("stage") == "execution"
                and "opened" in (l.get("message") or ""))
    total = blocked + taken
    # most common block reasons (text after the em dash, before the parenthesis)
    from collections import Counter
    reasons: Counter = Counter()
    for l in logs:
        if l.get("stage") == "brain":
            msg = l.get("message") or ""
            r = msg.split("blocked — ", 1)[-1].split("(")[0].strip() if "blocked — " in msg else "blocked"
            reasons[r] += 1

    # blocked counts per symbol (from the brain-stage decision log)
    blocked_by_sym: Counter = Counter()
    for l in logs:
        if l.get("stage") == "brain" and l.get("symbol"):
            blocked_by_sym[l["symbol"]] += 1

    return {
        "strategy": _wa.engine.strategy_label,
        "health": health.to_dict(),
        "brain": {
            "blocked": blocked, "taken": taken, "total": total,
            "block_rate": round(blocked / total * 100, 1) if total else 0.0,
            "top_reasons": dict(reasons.most_common(6)),
        },
        "breakdown": _wa._health_breakdown(_wa.paper.history(), blocked_by_sym),
    }
