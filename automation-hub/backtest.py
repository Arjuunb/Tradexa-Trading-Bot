"""Backtest + walk-forward for the DecisionBrain on real OHLC data.

Loads a CSV of candles, runs the SAME DecisionBrain the live engine uses, and
reports the metrics that decide whether a strategy makes money — profit factor,
expectancy (avg R), net return — not just win rate.

Usage:
    python backtest.py data.csv                 # full-sample backtest
    python backtest.py data.csv --group 16      # resample 15m -> 4h (16 bars)
    python backtest.py data.csv --group 16 --walk-forward
    python backtest.py data.csv --threshold 0.5 --rr 2.5

CSV columns: open, high, low, close and either timestamp_ms or datetime(_utc).
Validated reference (ETH 15m -> 4h, walk-forward): ~33% win rate, profit
factor ~1.2 out-of-sample — a real trend edge. High win rate is NOT the goal;
positive expectancy is.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.types import Bar, SignalType
from strategies.brain_strategy import DecisionBrain
from strategies.donchian_strategy import DonchianStrategy
from strategies.supertrend_strategy import SupertrendStrategy

TAKER_FEE = 0.0004  # per side (Binance futures taker)


def make_strategy(name: str, threshold: float, rr: float):
    if name == "supertrend":
        return SupertrendStrategy("BT", rr_target=rr)
    if name == "donchian":
        return DonchianStrategy("BT", rr_target=rr)
    if name == "ensemble":
        from strategies.ensemble_strategy import ConfirmationEnsemble
        return ConfirmationEnsemble("BT", rr_target=rr)
    return DecisionBrain("BT", conviction_threshold=threshold, rr_target=rr)


def load_csv(path: str) -> list[Bar]:
    bars: list[Bar] = []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            if "timestamp_ms" in row and row["timestamp_ms"]:
                ts = datetime.fromtimestamp(int(row["timestamp_ms"]) / 1000, tz=timezone.utc)
            else:
                raw = row.get("datetime_utc") or row.get("datetime") or row.get("time")
                ts = datetime.fromisoformat(raw)
            bars.append(Bar(ts, float(row["open"]), float(row["high"]),
                            float(row["low"]), float(row["close"]),
                            float(row.get("volume", 0) or 0)))
    return bars


def resample(bars: list[Bar], group: int) -> list[Bar]:
    """Aggregate every ``group`` bars into one (e.g. 16 x 15m -> 4h)."""
    if group <= 1:
        return bars
    out: list[Bar] = []
    for i in range(0, len(bars) - group + 1, group):
        s = bars[i:i + group]
        out.append(Bar(s[-1].timestamp, s[0].open, max(b.high for b in s),
                       min(b.low for b in s), s[-1].close, sum(b.volume for b in s)))
    return out


@dataclass
class Metrics:
    trades: int
    win_rate: float
    profit_factor: float
    avg_r: float
    net_r: float
    max_dd_r: float

    def __str__(self) -> str:
        return (f"trades {self.trades} | win {self.win_rate:.1f}% | "
                f"PF {self.profit_factor:.2f} | avgR {self.avg_r:+.3f} | "
                f"netR {self.net_r:+.0f} | return@1%risk {self.net_r:+.0f}% | "
                f"maxDD {self.max_dd_r:.0f}R")


def _metrics(rs: list[float]) -> Metrics:
    if not rs:
        return Metrics(0, 0, 0, 0, 0, 0)
    wins = sum(1 for r in rs if r > 0)
    gp = sum(r for r in rs if r > 0)
    gl = -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return Metrics(len(rs), wins / len(rs) * 100, (gp / gl) if gl else 99.0,
                   sum(rs) / len(rs), sum(rs), dd)


def run(bars: list[Bar], *, strategy: str = "brain", threshold: float = 0.5,
        rr: float = 2.5, fee: float = TAKER_FEE, slippage: float = 0.0,
        with_index: bool = False):
    """Run a strategy over bars; return R-multiples per trade (hold to stop/TP).

    Each trade's R is reward/risk: +rr on a target hit, -1 on a stop, minus
    round-trip costs (``fee`` + ``slippage`` per side, as a fraction of price).
    """
    cost = fee + slippage
    brain = make_strategy(strategy, threshold, rr)
    pos = None
    out: list = []
    for i, b in enumerate(bars):
        if pos is not None:
            exited = False
            if pos["side"] == "long":
                if b.low <= pos["sl"]:
                    r, exited = -1.0, True
                elif b.high >= pos["tp"]:
                    r, exited = rr, True
            else:
                if b.high >= pos["sl"]:
                    r, exited = -1.0, True
                elif b.low <= pos["tp"]:
                    r, exited = rr, True
            if exited:
                r -= cost * pos["entry"] * 2 / pos["risk"]
                out.append((pos["i"], r) if with_index else r)
                pos = None
        if pos is None:
            sig = brain.on_bar(b)
            if sig is not None:
                risk = abs(sig.entry - sig.stop_loss)
                if risk > 0:
                    pos = {"side": "long" if sig.type == SignalType.LONG else "short",
                           "entry": sig.entry, "sl": sig.stop_loss, "tp": sig.take_profit,
                           "risk": risk, "i": i}
        else:
            brain.on_bar(b)  # keep indicators warm while in a position
    return out


def walk_forward(bars: list[Bar], *, strategy: str = "brain", train: int = 1500,
                 test: int = 750, fee: float = TAKER_FEE,
                 slippage: float = 0.0) -> tuple[Metrics, list]:
    """Optimise (threshold, rr) on each train window, trade the next unseen test
    window, roll forward. Returns aggregate out-of-sample metrics + per-fold rows."""
    grid = [(t, rr) for t in (0.4, 0.5, 0.6) for rr in (1.5, 2.0, 2.5, 3.0)]
    runs = {p: run(bars, strategy=strategy, threshold=p[0], rr=p[1], fee=fee,
                   slippage=slippage, with_index=True) for p in grid}
    oos: list[float] = []
    folds = []
    start = 0
    n = len(bars)
    while start + train + test <= n:
        a, b, c = start, start + train, start + train + test
        best = max(grid, key=lambda p: sum(r for idx, r in runs[p] if a <= idx < b))
        tt = [r for idx, r in runs[best] if b <= idx < c]
        oos += tt
        folds.append((bars[b].timestamp.date(), bars[c - 1].timestamp.date(), best, _metrics(tt)))
        start += test
    return _metrics(oos), folds


def main() -> None:
    ap = argparse.ArgumentParser(description="DecisionBrain backtest / walk-forward")
    ap.add_argument("csv")
    ap.add_argument("--group", type=int, default=1, help="bars per resampled candle (16 = 15m->4h)")
    ap.add_argument("--strategy", choices=("brain", "supertrend", "donchian", "ensemble"), default="brain")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--rr", type=float, default=2.5)
    ap.add_argument("--slippage", type=float, default=0.0, help="per-side slippage as fraction (e.g. 0.0002 = 2bps)")
    ap.add_argument("--walk-forward", action="store_true")
    args = ap.parse_args()

    bars = resample(load_csv(args.csv), args.group)
    print(f"{len(bars):,} bars  {bars[0].timestamp.date()} -> {bars[-1].timestamp.date()}  "
          f"[{args.strategy}, slip {args.slippage*100:.3f}%/side]")

    if args.walk_forward:
        agg, folds = walk_forward(bars, strategy=args.strategy, slippage=args.slippage)
        print("\nOut-of-sample folds (params chosen on prior window):")
        for d0, d1, p, m in folds:
            print(f"  {d0}->{d1}  thr{p[0]} rr{p[1]}  {m}")
        print(f"\nAGGREGATE OUT-OF-SAMPLE: {agg}")
    else:
        m = _metrics(run(bars, strategy=args.strategy, threshold=args.threshold,
                         rr=args.rr, slippage=args.slippage))
        print(f"strategy {args.strategy} · threshold {args.threshold} · rr {args.rr}\n{m}")


if __name__ == "__main__":
    main()
