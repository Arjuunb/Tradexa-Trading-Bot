"""Server-side grid trading engine (paper, 24/7).

A grid is split into gaps between adjacent levels; each gap buys at its bottom
and sells at its top, booking profit net of fees. At start it SEEDS inventory
for every level above the current price (a real grid commits capital upfront).
``GridBot`` is the pure, deterministic state machine (mirrors the browser
engine in the dashboard); ``GridRunner`` wraps it with a background thread that
polls real candles and advances the grid over each newly-CLOSED candle — so it
keeps trading with no browser open. Paper only; nothing here is fabricated.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def level_prices(lower: float, upper: float, n: int, geometric: bool) -> list[float]:
    if n < 2 or lower <= 0 or upper <= lower:
        return []
    if geometric:
        r = (upper / lower) ** (1.0 / (n - 1))
        return [lower * (r ** i) for i in range(n)]
    step = (upper - lower) / (n - 1)
    return [lower + i * step for i in range(n)]


class GridBot:
    """Pure grid state machine. ``on_candle`` advances one closed candle and
    returns the fills it produced. Deterministic — easy to test and snapshot."""

    def __init__(self, *, symbol: str, timeframe: str, lower: float, upper: float,
                 levels: int, geometric: bool, investment: float,
                 leverage: float = 1.0, fee_pct: float = 0.04, start_price: float,
                 _skip_seed: bool = False):
        self.symbol = symbol
        self.timeframe = timeframe
        self.lower = float(lower)
        self.upper = float(upper)
        self.levels = int(levels)
        self.geometric = bool(geometric)
        self.investment = float(investment)
        self.leverage = float(leverage)
        self.fee_pct = float(fee_pct)
        self.start_price = float(start_price)
        prices = level_prices(self.lower, self.upper, self.levels, self.geometric)
        if len(prices) < 2:
            raise ValueError("grid needs at least 2 valid levels")
        self.order_value = (self.investment / (len(prices) - 1)) * self.leverage
        self.gaps: list[dict] = []
        self.realized = 0.0
        self.fees_paid = 0.0
        self.completed = 0
        self.buys = 0
        self.sells = 0
        self.fills: list[dict] = []
        self.last_price = self.start_price
        self.created_at = _now()
        if _skip_seed:
            return
        fee_rate = self.fee_pct / 100.0
        for i in range(len(prices) - 1):
            lo, hi = round(prices[i], 8), round(prices[i + 1], 8)
            if lo >= self.start_price:                 # above price -> seed inventory at start
                qty = self.order_value / self.start_price
                buy_fee = self.order_value * fee_rate
                self.fees_paid += buy_fee
                self.buys += 1
                self.gaps.append({"lo": lo, "hi": hi, "state": "holding", "qty": qty,
                                  "buy_price": self.start_price, "buy_fee": buy_fee})
            else:
                self.gaps.append({"lo": lo, "hi": hi, "state": "waiting_buy", "qty": 0.0,
                                  "buy_price": 0.0, "buy_fee": 0.0})

    # ------------------------------------------------------------------ engine
    def on_candle(self, low: float, high: float, close: float, ts: str) -> list[dict]:
        fee_rate = self.fee_pct / 100.0
        new_fills: list[dict] = []
        for g in self.gaps:
            if g["state"] == "waiting_buy" and low <= g["lo"]:          # price dropped to buy level
                qty = self.order_value / g["lo"]
                buy_fee = self.order_value * fee_rate
                g.update(qty=qty, buy_price=g["lo"], buy_fee=buy_fee, state="holding")
                self.fees_paid += buy_fee
                self.buys += 1
                new_fills.append(self._fill(ts, "BUY", g["lo"], qty, -buy_fee))
            if g["state"] == "holding" and high >= g["hi"]:             # price rose to sell level
                sell_fee = g["qty"] * g["hi"] * fee_rate
                pnl = g["qty"] * (g["hi"] - g["buy_price"]) - g["buy_fee"] - sell_fee
                self.realized += pnl
                self.fees_paid += sell_fee
                self.completed += 1
                self.sells += 1
                new_fills.append(self._fill(ts, "SELL", g["hi"], g["qty"], pnl))
                g.update(qty=0.0, buy_price=0.0, buy_fee=0.0, state="waiting_buy")
        self.last_price = close
        return new_fills

    def _fill(self, ts: str, side: str, price: float, qty: float, pnl: float) -> dict:
        f = {"t": ts, "side": side, "price": round(price, 6), "qty": round(qty, 8), "pnl": round(pnl, 6)}
        self.fills.insert(0, f)
        del self.fills[100:]
        return f

    def unrealized(self, price: Optional[float] = None) -> float:
        p = self.last_price if price is None else price
        return sum(g["qty"] * (p - g["buy_price"]) for g in self.gaps if g["state"] == "holding")

    def inventory(self) -> tuple[int, float]:
        lots = sum(1 for g in self.gaps if g["state"] == "holding")
        cost = sum(g["qty"] * g["buy_price"] for g in self.gaps if g["state"] == "holding")
        return lots, cost

    def summary(self, price: Optional[float] = None) -> dict:
        p = self.last_price if price is None else price
        up = self.unrealized(p)
        lots, cost = self.inventory()
        return {
            "symbol": self.symbol, "timeframe": self.timeframe,
            "lower": self.lower, "upper": self.upper, "levels": self.levels,
            "geometric": self.geometric, "investment": self.investment, "leverage": self.leverage,
            "fee_pct": self.fee_pct, "start_price": self.start_price,
            "realized": round(self.realized, 4), "unrealized": round(up, 4),
            "net": round(self.realized + up, 4), "completed": self.completed,
            "buys": self.buys, "sells": self.sells, "fees_paid": round(self.fees_paid, 4),
            "inventory_lots": lots, "inventory_cost": round(cost, 2),
            "last_price": p, "fills": self.fills[:20],
        }

    # --------------------------------------------------------------- snapshot
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "timeframe": self.timeframe, "lower": self.lower, "upper": self.upper,
            "levels": self.levels, "geometric": self.geometric, "investment": self.investment,
            "leverage": self.leverage, "fee_pct": self.fee_pct, "start_price": self.start_price,
            "order_value": self.order_value, "gaps": self.gaps, "realized": self.realized,
            "fees_paid": self.fees_paid, "completed": self.completed, "buys": self.buys,
            "sells": self.sells, "fills": self.fills, "last_price": self.last_price, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GridBot":
        b = cls(symbol=d["symbol"], timeframe=d["timeframe"], lower=d["lower"], upper=d["upper"],
                levels=d["levels"], geometric=d["geometric"], investment=d["investment"],
                leverage=d.get("leverage", 1.0), fee_pct=d.get("fee_pct", 0.04),
                start_price=d["start_price"], _skip_seed=True)
        b.order_value = d.get("order_value", b.order_value)
        b.gaps = d.get("gaps", [])
        b.realized = d.get("realized", 0.0)
        b.fees_paid = d.get("fees_paid", 0.0)
        b.completed = d.get("completed", 0)
        b.buys = d.get("buys", 0)
        b.sells = d.get("sells", 0)
        b.fills = d.get("fills", [])
        b.last_price = d.get("last_price", b.start_price)
        b.created_at = d.get("created_at", _now())
        return b


class GridRunner:
    """Runs a GridBot on a background thread, advancing it over each newly-closed
    real candle from ``fetcher(symbol, timeframe, n) -> (bars, source)``. Logs
    fills to the ledger and calls ``persist(snapshot)`` on every change so the
    grid survives a restart."""

    def __init__(self, bot: GridBot, fetcher: Callable, ledger,
                 *, interval: float = 30.0, persist: Optional[Callable[[dict], None]] = None):
        self.bot = bot
        self.fetcher = fetcher
        self.ledger = ledger
        self.interval = interval
        self.persist = persist
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.running = False
        self.started_at: Optional[str] = None
        self.last_ts: Optional[str] = None
        self.last_source: Optional[str] = None
        self.feed_error: Optional[str] = None

    def start(self) -> bool:
        if self.running:
            return False
        self._stop.clear()
        self.running = True
        self.started_at = _now()
        self._thread = threading.Thread(target=self._run, name="grid-runner", daemon=True)
        self._thread.start()
        try:
            self.ledger.log(level="info", stage="grid",
                            message=f"Grid started on {self.bot.symbol} {self.bot.timeframe} "
                                    f"({self.bot.levels} levels, {self.bot.leverage:g}x)", symbol=self.bot.symbol)
        except Exception:  # noqa: BLE001
            pass
        return True

    def stop(self) -> bool:
        if not self.running:
            return False
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=5)
        self.running = False
        try:
            self.ledger.log(level="info", stage="grid", message="Grid stopped", symbol=self.bot.symbol)
        except Exception:  # noqa: BLE001
            pass
        self._save()
        return True

    def _save(self) -> None:
        if self.persist:
            try:
                self.persist(self.snapshot())
            except Exception:  # noqa: BLE001 — persistence must never break the runner
                pass

    def _run(self) -> None:
        # warm: only act on candles that CLOSE after we start (start from now)
        try:
            bars, src = self.fetcher(self.bot.symbol, self.bot.timeframe, 3)
            self.last_source = src
            if bars and len(bars) >= 2 and self.last_ts is None:
                self.last_ts = bars[-2].timestamp.isoformat()
        except Exception as e:  # noqa: BLE001
            self.feed_error = f"{type(e).__name__}: {e}"
        while not self._stop.is_set():
            try:
                bars, src = self.fetcher(self.bot.symbol, self.bot.timeframe, 80)
                self.last_source = src
                self.feed_error = None if (src or "").startswith("live") else f"feed not live ('{src}')"
                closed = bars[:-1] if len(bars) > 1 else []
                if self.last_ts is None and closed:
                    # never warmed (the start-time fetch failed) — seed from the
                    # latest closed candle so we only ever act on candles that close
                    # AFTER now, instead of replaying the whole 80-bar history as
                    # live fills (which would fabricate PnL). Warm this tick, act next.
                    self.last_ts = closed[-1].timestamp.isoformat()
                    self._stop.wait(self.interval)
                    continue
                changed = False
                for b in closed:
                    ts = b.timestamp.isoformat()
                    if ts > self.last_ts:
                        fills = self.bot.on_candle(b.low, b.high, b.close, ts)
                        self.last_ts = ts
                        changed = True
                        for f in fills:
                            try:
                                self.ledger.log(level="info", stage="grid", symbol=self.bot.symbol,
                                                message=f"Grid {f['side']} {self.bot.symbol} @ {f['price']} "
                                                        + (f"(+{f['pnl']:.2f})" if f["side"] == "SELL" else ""))
                            except Exception:  # noqa: BLE001
                                pass
                if changed:
                    self._save()
            except Exception as e:  # noqa: BLE001 — a fetch hiccup shouldn't kill the grid
                self.feed_error = f"{type(e).__name__}: {e}"
            self._stop.wait(self.interval)

    def snapshot(self) -> dict:
        return {"running": self.running, "last_ts": self.last_ts, "started_at": self.started_at,
                "bot": self.bot.to_dict()}

    def status(self) -> dict:
        st = self.bot.summary()
        st.update({"running": self.running, "last_ts": self.last_ts, "started_at": self.started_at,
                   "data_source": self.last_source, "feed_error": self.feed_error})
        return st

    @classmethod
    def from_snapshot(cls, snap: dict, fetcher: Callable, ledger, **kw) -> "GridRunner":
        r = cls(GridBot.from_dict(snap["bot"]), fetcher, ledger, **kw)
        r.last_ts = snap.get("last_ts")
        r.started_at = snap.get("started_at")
        return r
