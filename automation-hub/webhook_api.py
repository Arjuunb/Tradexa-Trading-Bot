"""Webhook + ledger API (Kyros Phase 1).

Public, secret-gated endpoint that receives TradingView alerts and runs the
signal pipeline (dedup -> risk -> sizing -> paper execution -> ledger). Plus
emergency controls (Pause/Stop/Resume) and read endpoints the dashboard uses.

Mounted on the existing FastAPI app via ``app.include_router(router)``.
"""
from __future__ import annotations

import hmac
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from config import settings
from data.ledger import get_ledger
from execution.paper_engine import PaperExecutionEngine
from services.auto_engine import AutoStrategyEngine
from services.controls import TradingControl
from services.market_quality import MarketQualityConfig, MarketQualityGate
from services.signal_pipeline import SignalPipeline

# --- Phase 1 singletons (one ledger / paper account / control switch) ---
_BOOT = time.time()
ledger = get_ledger(settings.ledger_path)
controls = TradingControl()
from services.fill_model import from_env as _fill_from_env  # noqa: E402
paper = PaperExecutionEngine(ledger, settings.starting_cash, fill_model=_fill_from_env())
from services.execution_quality import ExecutionQuality  # noqa: E402
exec_quality = ExecutionQuality()
paper.quality = exec_quality
quality = MarketQualityGate(MarketQualityConfig(
    min_stop_distance_pct=settings.quality_min_stop_pct,
    max_stop_distance_pct=settings.quality_max_stop_pct,
    max_signal_age_s=settings.quality_max_signal_age_s,
    max_spread_bps=settings.quality_max_spread_bps,
))
pipeline = SignalPipeline(
    ledger, paper, controls,
    equity=settings.starting_cash,
    risk_per_trade_pct=settings.risk_per_trade_pct,
    exposure_limit_pct=settings.exposure_limit_pct,
    dedup_window_s=settings.dedup_window_s,
    quality=quality,
    max_drawdown_pct=settings.max_drawdown_pct,
    max_open_positions=settings.max_open_positions,
    max_daily_loss_pct=settings.max_daily_loss_pct,
    session_start=settings.session_start,
    session_end=settings.session_end,
    max_weekly_loss_pct=settings.max_weekly_loss_pct,
    max_trades_per_day=settings.max_trades_per_day,
    max_consecutive_losses=settings.max_consecutive_losses,
    cooldown_after_loss_min=settings.cooldown_after_loss_min,
    trading_days_mask=settings.trading_days_mask,
)
# Telegram notifications (best-effort) -> routed from pipeline events.
from services.notifier import Notifier  # noqa: E402
notifier = Notifier(settings.telegram_token, settings.telegram_chat_id)
pipeline.notifier = notifier.dispatch

# Multi-channel alerts (Telegram / Discord / Email) — credentials in a local
# JSON store next to the provider settings (gitignored), or env vars.
from services.alerts import AlertChannels  # noqa: E402
import os as _os  # noqa: E402
alert_channels = AlertChannels(notifier, _os.path.join(_os.path.dirname(settings.providers_path), "alert_channels.json"))

# Economic-event calendar (user-set / provider-fed upcoming events).
from services.econ_guard import EconCalendar  # noqa: E402
econ_calendar = EconCalendar(_os.path.join(_os.path.dirname(settings.providers_path), "econ_events.json"))
# Event-risk gate: the pipeline halts new entries in the blackout window
# around high-impact events and halves size in the caution window.
pipeline.econ_events = econ_calendar.events
# Allocator tilt: size up symbols with a proven recent live record (bounded).
from services.allocator import risk_weights as _alloc_weights  # noqa: E402
pipeline.allocator = lambda sym: _alloc_weights(paper.history(), [sym]).get(sym.upper(), 1.0)

# Trade journal (auto-entries from closed trades, human-editable).
from services.journal import JournalStore  # noqa: E402
journal_store = JournalStore(_os.path.join(_os.path.dirname(settings.providers_path), "journal.json"))

# Persistent market memory (mined per-strategy stat snapshots).
from services.memory import MemoryStore  # noqa: E402
memory_store = MemoryStore(_os.path.join(_os.path.dirname(settings.providers_path), "memory.json"))

# Self-learning loop: the bot studies its own losing trades after every close
# and applies bounded, expiring corrections (see services/learning.py).
from services.learning import LearningBook  # noqa: E402
learning_book = LearningBook(_os.path.join(_os.path.dirname(settings.providers_path), "learning.json"))
pipeline.learning = learning_book

# Counterfactual tracker: every veto is followed as a virtual trade so each
# rule is graded by what it actually blocked; rules that block winners get
# falsified instead of surviving on their expiry timer.
from services.counterfactual import CounterfactualTracker  # noqa: E402
counterfactual = CounterfactualTracker(
    _os.path.join(_os.path.dirname(settings.providers_path), "counterfactual.json"))
pipeline.counterfactual = counterfactual

# Decision journal: the full explainable record of every bot trade — entry
# reasoning, rule checklist, market snapshot, risk check, exit, review and
# evolution notes, all from REAL decision data.
from data.journal_store import JournalStore as DecisionJournalStore  # noqa: E402
from services.decision_journal import DecisionJournal  # noqa: E402
decision_journal_store = DecisionJournalStore(settings.journal_db)
pipeline.journal = DecisionJournal(decision_journal_store)

# Live-trading readiness gate: an enforced checklist between paper and live.
# Live stays locked by default; this only reports real state, never fakes it.
from services.safety_gate import SafetyState  # noqa: E402
safety_state = SafetyState(settings.safety_state_path)

# Skipped-trade log: every rejected setup with its failed gate + market
# snapshot, so a quiet bot is explainable and searchable (not a black box).
from data.skipped_store import SkippedTradeStore  # noqa: E402
skipped_store = SkippedTradeStore(settings.skipped_db)
pipeline.skipped = skipped_store

# Unified decision store: every evaluated signal becomes a persisted decision
# object (accepted or rejected) BEFORE any trade is placed.
from data.decision_store import DecisionStore  # noqa: E402
decision_store = DecisionStore(settings.decisions_db)

# Persistent paper-account state: capital / equity survive logout, refresh and
# restart (with HUB_DATA_DIR). initial_capital is seeded once from the configured
# starting cash; the SAVED value wins over the default on every restart.
from data.account_store import AccountStore  # noqa: E402
account_store = AccountStore(settings.account_db)
account_store.seed_if_empty(settings.starting_cash)
# the persisted initial capital drives the paper account (not the env default)
paper.starting_balance = account_store.initial_capital()
paper.account_store = account_store
# reconcile the snapshot from the ledger's real closed trades on boot
paper._persist_account_snapshot()

# Persistent market prefs: favorites / pins / watchlists survive logout + restart.
from data.watchlist_store import WatchlistStore  # noqa: E402
watchlist_store = WatchlistStore(settings.watchlist_db)

# Permanent Trading Memory: every CLOSED trade is composed into an 8-category
# memory (trade info, market context, technicals, strategy, execution, emotion,
# outcome, AI reflection) and remembered forever unless explicitly deleted.
# Composed from REAL captured data — the decision journal, the decision object
# and the ledger; uncaptured fields are marked honestly, never invented.
from data.trade_memory_store import TradeMemoryStore  # noqa: E402
from services.trade_memory_manager import TradeMemoryManager  # noqa: E402
trade_memory_store = TradeMemoryStore(settings.trade_memory_db)
trade_memory = TradeMemoryManager(
    trade_memory_store, decision_journal_store, decision_store,
    exchange=_os.environ.get("HUB_EXCHANGE", "paper"),
    starting_balance=account_store.initial_capital())
# the pipeline calls this after the decision journal closes a trade
pipeline.trade_memory = trade_memory
# import already-closed journal trades so the memory isn't empty on first boot
trade_memory.backfill()

# Broker layer (#14) — one interface, paper executable, live locked.
from services.broker import BrokerRegistry  # noqa: E402
broker_registry = BrokerRegistry()

# Research lab (#15) — saved A/B experiments + reports.
from services.research import ResearchStore  # noqa: E402
research_store = ResearchStore(_os.path.join(_os.path.dirname(settings.providers_path), "research.json"))

# Bot OS — the service/event layer the engines communicate through.
from services.bot_os import BotOS  # noqa: E402
bot_os = BotOS()
bot_os.set_status_fn("Execution Engine", lambda: {"state": "up" if engine.status().get("running") else "idle",
                                                  "detail": "running" if engine.status().get("running") else "stopped"})
bot_os.set_status_fn("Strategy Engine", lambda: {"state": "up", "detail": settings.auto_strategy})
bot_os.bus.publish("system", "boot", {"msg": "Bot OS initialised"})

# Autonomous engine: real strategy signals -> the same pipeline (paper-only).
# Default brain is the multi-signal DecisionBrain; HUB_AUTO_STRATEGY=ema selects
# the simple EMA crossover instead.
def _make_strategy(symbol: str):
    s = settings.auto_strategy
    if s == "adaptive":
        # multi-strategy allocation: per-symbol pick from market memory
        from services.allocator import adaptive_factory
        return adaptive_factory(memory_store, settings.auto_timeframe)(symbol)
    if s == "ema":
        from strategies.ema_strategy import EMAStrategy
        return EMAStrategy(symbol)
    if s == "supertrend":
        from strategies.supertrend_strategy import SupertrendStrategy
        return SupertrendStrategy(symbol)
    if s == "donchian":
        from strategies.donchian_strategy import DonchianStrategy
        return DonchianStrategy(symbol)
    if s == "ensemble":
        from strategies.ensemble_strategy import ConfirmationEnsemble
        return ConfirmationEnsemble(symbol)
    from strategies.brain_strategy import DecisionBrain
    return DecisionBrain(symbol)


# WebSocket feed (live mode): push candles with REST fallback. Starts only if
# ccxt.pro is available; otherwise the fetcher is a pure REST pass-through and
# the watchdog/status endpoints report the degraded mode honestly.
from data.ws_feed import WebSocketFeed  # noqa: E402
from services.auto_engine import _default_fetcher  # noqa: E402
ws_feed = WebSocketFeed(list(settings.auto_symbols), timeframe=settings.auto_timeframe)
if settings.use_live_data:
    ws_feed.start()

engine = AutoStrategyEngine(
    pipeline, paper, ledger,
    symbols=list(settings.auto_symbols),
    timeframe=settings.auto_timeframe,
    interval=settings.auto_interval,
    strategy_factory=_make_strategy,
    live=settings.use_live_data,
    live_poll_s=settings.live_poll_s,
    fetcher=ws_feed.make_fetcher(_default_fetcher) if settings.use_live_data else None,
)
engine.counterfactual = counterfactual   # resolve vetoed trades on live bars
engine.decisions = decision_store        # persist every accept/reject decision

# Explainable Trading: one complete Decision Report per analysis cycle —
# including WAIT candles — so the bot never trades or skips silently.
from data.cycle_store import CycleStore  # noqa: E402
cycle_store = CycleStore(settings.cycles_db)
engine.reports = cycle_store

# Semi-auto / signal trading modes: the human-approval queue for entries.
from services.approvals import ApprovalStore  # noqa: E402
approvals = ApprovalStore(ttl_s=int(_os.environ.get("HUB_APPROVAL_TTL_S", "900")))
engine.approvals = approvals

# Watchdog: alerts (ledger + Telegram) when the feed stalls, the engine thread
# dies, or the stream degrades to REST. Heartbeat shown at /ops/watchdog.
from services.watchdog import Watchdog  # noqa: E402
watchdog = Watchdog(engine, ledger, notifier.dispatch, ws_feed=ws_feed)
watchdog.start()

# Daily report + nightly backup: one honest digest to Telegram per UTC day
# (HUB_DAILY_REPORT_HOUR, default 08:00 UTC; -1 disables) and a pruned
# snapshot of every db/json store under DATA_DIR/backups.
from services.backup import backup_now as _backup_now  # noqa: E402
from services.daily_report import DailyTasks, build_report  # noqa: E402
import config as _config  # noqa: E402


def _daily_report_data() -> dict:
    return build_report(history=paper.history(), positions=paper.positions(),
                        balance=paper.balance(), starting_balance=paper.starting_balance,
                        learning_report=learning_book.report(),
                        watchdog_status=watchdog.status(), engine_status=engine.status(),
                        counterfactual_report=counterfactual.report())


_last_retune: dict = {}


def _auto_retune_check() -> None:
    """Nightly: if the live record has diverged from the backtest promise and
    nothing is auditioning yet, search for a retuned brain and shadow it."""
    global _last_retune
    if engine.shadow is not None:
        return
    from services.retune import retune
    from services.track_record import track_record
    tr = track_record(paper.history(), strategy="Decision Brain",
                      symbol=engine.symbols[0], timeframe=engine.timeframe)
    res = retune(engine, notifier.dispatch, timeframe=engine.timeframe,
                 track_verdict=tr.get("verdict"))
    if res.get("ran"):
        _last_retune = res
        ledger.log(level="info", stage="research",
                   message=f"Auto-retune: {res.get('verdict')} — {res.get('detail', '')[:160]}")


def _memory_review() -> None:
    """Nightly pattern recognition over the permanent trade memory (also rolls
    up weekly/monthly/yearly reviews). Real stats only; never blocks."""
    try:
        res = trade_memory.run_reviews()
        ledger.log(level="info", stage="research",
                   message=f"Trade-memory review: {res.get('memories', 0)} memories, "
                           f"{len(res.get('ran', []))} periods refreshed")
    except Exception as e:  # noqa: BLE001
        ledger.log(level="warning", stage="research",
                   message=f"Trade-memory review failed: {type(e).__name__}")


# Retention pruning (M-6): cap the append-only tables each night so a
# persistent disk never fills. Trade rows are never pruned — they are the record.
def _retention_prune() -> None:
    keep = int(_os.environ.get("HUB_RETENTION_ROWS", "20000"))
    try:
        led = ledger.prune(keep_logs=keep * 2, keep_alerts=max(2000, keep // 2),
                           keep_events=keep)
        dec = decision_store.prune(keep=keep)
        skp = skipped_store.prune(keep=keep)
        ledger.log(level="info", stage="ops",
                   message=f"Retention prune: ledger={led} decisions={dec} skipped={skp}")
    except Exception as e:  # noqa: BLE001 — pruning must never crash the nightly run
        ledger.log(level="warning", stage="ops", message=f"Retention prune failed: {e}")


# Storage durability (H-1): assess whether state survives a redeploy and warn
# LOUDLY at boot if it does not, so no one runs on disposable storage silently.
from services.storage_health import assess as _assess_storage, boot_banner as _storage_banner  # noqa: E402
from data.ledger import SUPABASE_STATUS as _SUPA  # noqa: E402


def storage_assessment() -> dict:
    return _assess_storage(
        data_dir=str(_config.DATA_DIR),
        hub_data_dir_set=bool(_os.environ.get("HUB_DATA_DIR")),
        on_cloud=bool(_os.environ.get("RENDER") or _os.environ.get("DYNO")),
        supabase_connected=bool(_SUPA.get("connected")))


_boot_storage = storage_assessment()
_boot_banner = _storage_banner(_boot_storage)
if _boot_banner:
    import sys as _sys
    print(_boot_banner, file=_sys.stderr, flush=True)
    ledger.log(level="warning", stage="ops",
               message=(_boot_storage["warning"] or "Storage not fully durable"))


daily_tasks = DailyTasks(
    notifier.send_async, _daily_report_data,
    hour=int(_os.environ.get("HUB_DAILY_REPORT_HOUR", "8")),
    extra=[lambda: ledger.log(level="info", stage="ops",
                              message=f"Nightly backup: {_backup_now(str(_config.DATA_DIR))['snapshot']}"),
           _auto_retune_check,
           _memory_review,
           _retention_prune])
daily_tasks.start()

# Apply persisted runtime overrides on top of env defaults.
from services.runtime_settings import load_overrides, save_overrides  # noqa: E402


def _apply_setting(key: str, value) -> None:
    if key == "auto_strategy":
        settings.auto_strategy = str(value)
    elif key in ("notify_trades", "notify_risk"):
        setattr(notifier, key, bool(int(value)))
    elif key == "dedup_window_s":
        pipeline.dedup.window_seconds = int(value)
    elif key == "entry_mode":
        engine.entry_mode = "market" if str(value) == "market" else "limit"
    elif key == "daily_report_hour":
        daily_tasks.hour = int(value)
    elif key == "min_quality_score":
        engine.min_quality_score = int(value)
    elif key == "streak_risk_scaling":
        pipeline.streak_risk_scaling = bool(int(value))
    elif key == "trading_mode":
        engine.trading_mode = str(value) if str(value) in ("full", "semi", "signal") else "full" 
    elif key == "engine_timeframe":
        # applied before the startup event starts the engine, so a persisted
        # timeframe choice survives restarts/redeploys
        engine.timeframe = str(value)
    elif key == "engine_symbols":
        # persisted watchlist (comma-separated) — applied before engine start
        syms = [x.strip().upper() for x in str(value).split(",") if x.strip()]
        if syms:
            engine.symbols = syms
    elif key in ("max_open_positions", "session_start", "session_end",
                 "max_trades_per_day", "max_consecutive_losses", "cooldown_after_loss_min",
                 "trading_days_mask"):
        setattr(pipeline, key, int(value))
    else:  # *_pct float settings
        setattr(pipeline, key, float(value))


def _settings_snapshot() -> dict:
    return {
        "engine_timeframe": engine.timeframe,
        "risk_per_trade_pct": pipeline.risk_per_trade_pct,
        "exposure_limit_pct": pipeline.exposure_limit_pct,
        "max_drawdown_pct": pipeline.max_drawdown_pct,
        "max_open_positions": pipeline.max_open_positions,
        "dedup_window_s": pipeline.dedup.window_seconds,
        "max_daily_loss_pct": pipeline.max_daily_loss_pct,
        "session_start": pipeline.session_start,
        "session_end": pipeline.session_end,
        "max_weekly_loss_pct": pipeline.max_weekly_loss_pct,
        "max_trades_per_day": pipeline.max_trades_per_day,
        "max_consecutive_losses": pipeline.max_consecutive_losses,
        "cooldown_after_loss_min": pipeline.cooldown_after_loss_min,
        "trading_days_mask": pipeline.trading_days_mask,
        "notify_trades": 1 if notifier.notify_trades else 0,
        "notify_risk": 1 if notifier.notify_risk else 0,
        "auto_strategy": settings.auto_strategy,
        "entry_mode": engine.entry_mode,
        "daily_report_hour": daily_tasks.hour,
        "min_quality_score": engine.min_quality_score,
        "streak_risk_scaling": 1 if pipeline.streak_risk_scaling else 0,
        "engine_symbols": ",".join(engine.symbols),
        "trading_mode": engine.trading_mode,
    }


for _k, _v in load_overrides(settings.settings_path).items():
    _apply_setting(_k, _v)

router = APIRouter()


class SettingsUpdate(BaseModel):
    risk_per_trade_pct: Optional[float] = None
    exposure_limit_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    dedup_window_s: Optional[int] = None
    max_daily_loss_pct: Optional[float] = None
    session_start: Optional[int] = None
    session_end: Optional[int] = None
    max_weekly_loss_pct: Optional[float] = None
    max_trades_per_day: Optional[int] = None
    max_consecutive_losses: Optional[int] = None
    cooldown_after_loss_min: Optional[int] = None
    trading_days_mask: Optional[int] = None
    entry_mode: Optional[str] = None
    daily_report_hour: Optional[int] = None
    min_quality_score: Optional[int] = None
    streak_risk_scaling: Optional[bool] = None


class WebhookPayload(BaseModel):
    alert_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    side: str
    entry: float
    stop: Optional[float] = None
    timestamp: Optional[str] = None


def _check_secret(secret: Optional[str]) -> None:
    if not secret or not hmac.compare_digest(secret, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")
































def _export(rows: list, fields: list, fmt: str, name: str):
    import csv as _csv
    import io
    import json as _json
    from fastapi.responses import Response
    if fmt == "json":
        return Response(_json.dumps(rows, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename={name}.json"})
    buf = io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fields})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}.csv"})












class PositionSizeRequest(BaseModel):
    equity: float = 10000.0
    entry: float
    stop: Optional[float] = None
    side: str = "long"
    method: str = "percent"          # fixed | percent | atr | vol_adjusted
    risk_pct: float = 0.01
    fixed_risk: Optional[float] = None
    atr: Optional[float] = None
    atr_mult: float = 1.5
    leverage: float = 10.0
    vol_target_pct: float = 0.02






























class AlertChannelSave(BaseModel):
    discord_webhook: Optional[str] = None
    email_to: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None










class TagsBody(BaseModel):
    tags: list[str] = []






class CloneTemplateBody(BaseModel):
    template: str






class ResearchRunBody(BaseModel):
    name: str = "Experiment"
    spec_a: dict
    spec_b: dict
    bars: int = 4000
    label_a: str = "A"
    label_b: str = "B"
















class JournalEdit(BaseModel):
    notes: Optional[str] = None
    emotions: Optional[str] = None
    mistakes: Optional[list] = None
    lessons: Optional[list] = None
    tags: Optional[list] = None








def _broker_live_connected() -> bool:
    """True only if a real (non-paper) venue is actually connected."""
    try:
        return any(b.kind != "paper" and b.connected()
                   for b in broker_registry.brokers.values())
    except Exception:  # noqa: BLE001
        return False














class EconEvents(BaseModel):
    events: list = []
















class FillModelBody(BaseModel):
    model: str = "perfect"          # perfect | realistic
    spread_pct: float = 0.0004
    slippage_pct: float = 0.0003
    partial_fill_prob: float = 0.0
    reject_prob: float = 0.0


























































_STRATEGY_CATALOG = [
    {"key": "brain", "label": "Decision Brain",
     "desc": "Multi-factor trend: EMA trend + filter, momentum, RSI, regime; conviction-weighted sizing"},
    {"key": "supertrend", "label": "Supertrend", "desc": "ATR trend-following indicator"},
    {"key": "donchian", "label": "Donchian Breakout", "desc": "Classic Turtle channel breakout"},
    {"key": "ensemble", "label": "Confirmation Ensemble",
     "desc": "Trades only when 2 of 3 agree (EMA + Supertrend + Donchian)"},
    {"key": "ema", "label": "EMA Crossover", "desc": "Simple fast/slow EMA cross"},
    {"key": "smc", "label": "SMC (Smart Money)",
     "desc": "Liquidity sweep + CHoCH/BOS + FVG in line with higher-timeframe bias"},
]

# Reconcile the engine label with a persisted strategy choice: the overrides
# loop (which restores auto_strategy across restarts) runs before this catalog
# exists, so the label is corrected here — the factory itself already reads
# settings.auto_strategy live.
_persisted_strategy = next((s for s in _STRATEGY_CATALOG
                            if s["key"] == settings.auto_strategy), None)
if _persisted_strategy is not None:
    engine.strategy_label = _persisted_strategy["label"]






class NotifUpdate(BaseModel):
    notify_trades: Optional[bool] = None
    notify_risk: Optional[bool] = None








# ------------------------------------------------- custom strategy builder
from services.custom_store import CustomStore  # noqa: E402
custom_store = CustomStore(settings.custom_path)

# ------------------------------------------------- evolution engine stores
from services.lessons import LessonStore  # noqa: E402
from services.evolution import UpgradeStore, StrategyVersionStore  # noqa: E402
lesson_store = LessonStore(settings.lessons_path)
upgrade_store = UpgradeStore(settings.upgrades_path)
version_store = StrategyVersionStore(settings.versions_path)

# ------------------------------------------------- historical data engine
from data.historical import HistoricalStore  # noqa: E402
market_store = HistoricalStore(settings.market_db)
from data.backfill import BackfillJob  # noqa: E402
backfill_job = BackfillJob(market_store)

# ------------------------------------------------- market-context providers
from services.market_context import ProviderSettings  # noqa: E402
provider_settings = ProviderSettings(settings.providers_path)


class SimRequest(BaseModel):
    spec: dict
    bars: int = 3000






def _build_builtin(key: str, symbol: str):
    """Construct a built-in strategy object by catalog key."""
    if key == "smc":
        from strategies.smc_strategy import SMCStrategy
        return SMCStrategy(symbol)
    if key == "supertrend":
        from strategies.supertrend_strategy import SupertrendStrategy
        return SupertrendStrategy(symbol)
    if key == "donchian":
        from strategies.donchian_strategy import DonchianStrategy
        return DonchianStrategy(symbol)
    if key == "ensemble":
        from strategies.ensemble_strategy import ConfirmationEnsemble
        return ConfirmationEnsemble(symbol)
    if key == "ema":
        from strategies.ema_strategy import EMAStrategy
        return EMAStrategy(symbol)
    from strategies.brain_strategy import DecisionBrain
    return DecisionBrain(symbol)




class ControlSimRequest(BaseModel):
    strategy: str = "Decision Brain"
    symbol: str = "BTCUSDT"
    timeframe: str = "4h"
    tuning: dict = {}
    custom_spec: Optional[dict] = None
    bars: int = 4000
    macro: Optional[str] = None
    confirmation: Optional[str] = None
    realistic: bool = False






class ControlCompareRequest(BaseModel):
    a: dict
    b: dict
    bars: int = 4000




































def _replay_diag(rep: dict) -> dict:
    """Build a diagnosis-shaped dict from replay trades for the lessons engine."""
    from strategies.diagnosis import diagnose
    # replay trades use 'rr'; diagnose expects 'r'
    trades = [{**t, "r": t.get("rr")} for t in rep["trades"] if t.get("rr") is not None]
    return diagnose({"trades": trades, "total_trades": len(trades),
                     "win_rate": rep["stats"]["win_rate"], "profit_factor": rep["stats"]["profit_factor"],
                     "span_days": 30}, [])










class ExperimentRequest(BaseModel):
    base: dict
    variant: dict
    bars: int = 4000








def _default_base_spec(strategy: str, symbol: str = "BTCUSDT") -> dict:
    """A representative base spec to patch when no prior version exists."""
    return {"name": strategy, "symbol": symbol, "timeframe": "4h", "side": "long",
            "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"}]},
            "stop": {"type": "atr", "mult": 1.5, "period": 14},
            "target": {"type": "rr", "rr": 2.0}, "risk_per_trade_pct": 0.01,
            "min_score": 60, "quality_filter": True}




























class SymbolsUpdate(BaseModel):
    symbols: list[str]






class StrategySelect(BaseModel):
    strategy: str








def _session_of(hour: int) -> str:
    if 0 <= hour < 8:
        return "Asia"
    if 8 <= hour < 16:
        return "London"
    return "New York"


def _health_breakdown(history: list, blocked_by_sym) -> dict:
    """Per-symbol and per-session taken-trade performance (real P&L) + blocks."""
    def _hour(ts) -> int:
        try:
            return int(str(ts)[11:13])
        except (ValueError, TypeError):
            return -1

    sym: dict = {}
    sess: dict = {}
    for t in history:
        pnl = t.get("pnl") or 0.0
        s = sym.setdefault(t.get("symbol", "?"), {"trades": 0, "wins": 0, "net_pnl": 0.0})
        s["trades"] += 1; s["wins"] += 1 if pnl > 0 else 0; s["net_pnl"] += pnl
        h = _hour(t.get("opened_at"))
        if h >= 0:
            name = _session_of(h)
            g = sess.setdefault(name, {"trades": 0, "wins": 0, "net_pnl": 0.0})
            g["trades"] += 1; g["wins"] += 1 if pnl > 0 else 0; g["net_pnl"] += pnl

    def _rows(d, extra=None):
        out = []
        for name, v in d.items():
            row = {"name": name, "trades": v["trades"],
                   "win_rate": round(100 * v["wins"] / v["trades"], 0) if v["trades"] else 0.0,
                   "net_pnl": round(v["net_pnl"], 2)}
            if extra is not None:
                row["blocked"] = int(extra.get(name, 0))
            out.append(row)
        return sorted(out, key=lambda r: r["net_pnl"])

    # include symbols that were only ever blocked (never traded)
    by_symbol = _rows(sym, blocked_by_sym)
    seen = {r["name"] for r in by_symbol}
    for s, c in blocked_by_sym.items():
        if s not in seen:
            by_symbol.append({"name": s, "trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "blocked": int(c)})
    return {"by_symbol": by_symbol, "by_session": _rows(sess)}


# ── domain routers (endpoints live in routers/<domain>.py) ──
import routers.analytics  # noqa: E402
import routers.bots  # noqa: E402
import routers.engine  # noqa: E402
import routers.health  # noqa: E402
import routers.journal  # noqa: E402
import routers.paper  # noqa: E402
import routers.risk  # noqa: E402
import routers.settings  # noqa: E402
import routers.symbols  # noqa: E402
import routers.ai  # noqa: E402
router.include_router(routers.analytics.router)
router.include_router(routers.bots.router)
router.include_router(routers.engine.router)
router.include_router(routers.health.router)
router.include_router(routers.journal.router)
router.include_router(routers.paper.router)
router.include_router(routers.risk.router)
router.include_router(routers.settings.router)
router.include_router(routers.symbols.router)
router.include_router(routers.ai.router)
