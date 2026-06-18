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
import math
from collections import defaultdict
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
    if name == "smc":
        from strategies.smc_strategy import SMCStrategy
        return SMCStrategy("BT", rr_target=rr)
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


def oos_trades(bars: list[Bar], *, strategy: str = "brain", train: int = 1500,
               test: int = 750, fee: float = TAKER_FEE, slippage: float = 0.0):
    """Ordered (timestamp, R) of every out-of-sample trade in the walk-forward."""
    grid = [(t, rr) for t in (0.4, 0.5, 0.6) for rr in (1.5, 2.0, 2.5, 3.0)]
    runs = {p: run(bars, strategy=strategy, threshold=p[0], rr=p[1], fee=fee,
                   slippage=slippage, with_index=True) for p in grid}
    out = []
    start, n = 0, len(bars)
    while start + train + test <= n:
        a, b, c = start, start + train, start + train + test
        best = max(grid, key=lambda p: sum(r for idx, r in runs[p] if a <= idx < b))
        out += [(bars[idx].timestamp, r) for idx, r in runs[best] if b <= idx < c]
        start += test
    out.sort(key=lambda x: x[0])
    return out


def performance_report(bars: list[Bar], *, strategy: str = "brain",
                       train: int = 1500, test: int = 750,
                       fee: float = TAKER_FEE, slippage: float = 0.0002,
                       risk_per_trade: float = 0.01) -> dict:
    """Full out-of-sample performance + risk stats (the numbers that matter)."""
    tr = oos_trades(bars, strategy=strategy, train=train, test=test, fee=fee, slippage=slippage)
    if not tr:
        return {}
    R = [r for _, r in tr]
    n = len(R)
    wins = [r for r in R if r > 0]
    losses = [r for r in R if r < 0]
    # equity (R) for drawdown + losing streak
    eq = peak = dd = 0.0
    streak = worst_streak = 0
    for r in R:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    years = max((tr[-1][0] - tr[0][0]).days / 365.25, 1e-9)
    mean = sum(R) / n
    sd = (sum((r - mean) ** 2 for r in R) / n) ** 0.5
    sharpe = (mean / sd) * math.sqrt(n / years) if sd else 0.0
    mon = defaultdict(float)
    for ts, r in tr:
        mon[(ts.year, ts.month)] += r
    pos_months = sum(1 for v in mon.values() if v > 0)
    # $ equity compounding `risk_per_trade` of equity per trade
    bal = 10_000.0
    for r in R:
        bal *= (1 + risk_per_trade * r)
    cagr = (bal / 10_000.0) ** (1 / years) - 1
    return {
        "start": tr[0][0].date().isoformat(), "end": tr[-1][0].date().isoformat(),
        "years": round(years, 1), "trades": n,
        "win_rate": len(wins) / n * 100,
        "profit_factor": (sum(wins) / -sum(losses)) if losses else float("inf"),
        "expectancy_r": mean,
        "avg_win_r": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss_r": (sum(losses) / len(losses)) if losses else 0.0,
        "best_r": max(R), "worst_r": min(R), "total_r": sum(R),
        "max_drawdown_r": dd, "longest_losing_streak": worst_streak,
        "sharpe": sharpe, "positive_months": pos_months, "months": len(mon),
        "end_balance": bal, "cagr_pct": cagr * 100,
    }


def _print_report(label: str, s: dict) -> None:
    if not s:
        print("No out-of-sample trades.")
        return
    pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
    print(f"=== {label} — OUT-OF-SAMPLE (walk-forward, fees+slippage) ===")
    print(f"Period:                {s['start']} -> {s['end']}  ({s['years']}y)")
    print(f"Trades:                {s['trades']}")
    print(f"Win rate:              {s['win_rate']:.1f}%")
    print(f"Profit factor:         {pf}")
    print(f"Expectancy:            {s['expectancy_r']:+.3f}R / trade")
    print(f"Avg win / loss:        +{s['avg_win_r']:.2f}R / {s['avg_loss_r']:.2f}R")
    print(f"Best / worst trade:    +{s['best_r']:.2f}R / {s['worst_r']:.2f}R")
    print(f"Total:                 {s['total_r']:+.0f}R")
    print(f"Max drawdown:          {s['max_drawdown_r']:.0f}R")
    print(f"Longest losing streak: {s['longest_losing_streak']} trades")
    print(f"Sharpe (annualized):   {s['sharpe']:.2f}")
    print(f"Positive months:       {s['positive_months']}/{s['months']} "
          f"({s['positive_months'] / s['months'] * 100:.0f}%)")
    print(f"$10k @1% risk/trade ->  ${s['end_balance']:,.0f}   (CAGR {s['cagr_pct']:.1f}%/yr)")


def main() -> None:
    ap = argparse.ArgumentParser(description="DecisionBrain backtest / walk-forward")
    ap.add_argument("csv")
    ap.add_argument("--group", type=int, default=1, help="bars per resampled candle (16 = 15m->4h)")
    ap.add_argument("--strategy", choices=("brain", "supertrend", "donchian", "ensemble"), default="brain")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--rr", type=float, default=2.5)
    ap.add_argument("--slippage", type=float, default=0.0, help="per-side slippage as fraction (e.g. 0.0002 = 2bps)")
    ap.add_argument("--walk-forward", action="store_true")
    ap.add_argument("--report", action="store_true", help="full out-of-sample performance + risk report")
    args = ap.parse_args()

    bars = resample(load_csv(args.csv), args.group)
    print(f"{len(bars):,} bars  {bars[0].timestamp.date()} -> {bars[-1].timestamp.date()}  "
          f"[{args.strategy}, slip {args.slippage*100:.3f}%/side]\n")

    if args.report:
        slip = args.slippage or 0.0002   # default to a realistic 2bps for the report
        _print_report(f"{args.strategy}", performance_report(bars, strategy=args.strategy, slippage=slip))
    elif args.walk_forward:
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
