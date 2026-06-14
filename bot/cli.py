"""Real CLI: ``python -m bot {backtest,multi,walkforward,validate,demo,dashboard}``.

Design
------
- Stdlib only. ``yaml`` is *optionally* required by config-driven sub-commands;
  ``demo`` and direct CSV/synthetic runs work without it.
- Each sub-command is a small function so it's trivially unit-testable.
- ``main()`` returns an int exit code so callers (incl. ``__main__``) just do
  ``sys.exit(main())``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


def _build_subparsers(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True)

    # ---- backtest ----
    pb = sub.add_parser("backtest", help="Run a single-symbol backtest")
    g = pb.add_mutually_exclusive_group(required=True)
    g.add_argument("--config", help="Path to YAML config")
    g.add_argument("--csv", help="Path to OHLCV CSV (uses defaults for params)")
    g.add_argument("--demo", action="store_true",
                   help="Use bundled BTC-USD sample data")
    pb.add_argument("--symbol", default="BTC-USD",
                    help="Symbol label (used with --csv/--demo)")
    pb.add_argument("--report", help="Write HTML report to this path")
    pb.add_argument("--equity-csv", help="Write equity curve CSV to this path")
    pb.add_argument("--trades-jsonl", help="Write trades JSONL to this path")
    pb.add_argument("--json", action="store_true",
                    help="Print results as JSON instead of human summary")

    # ---- multi ----
    pm = sub.add_parser("multi",
                        help="Multi-symbol backtest from bundled samples")
    pm.add_argument("--symbols", default="BTC-USD,ETH-USD,AAPL",
                    help="Comma-separated symbols matching files in data/samples/")
    pm.add_argument("--report", help="Write HTML report to this path")
    pm.add_argument("--json", action="store_true")

    # ---- walkforward ----
    pw = sub.add_parser("walkforward", help="Walk-forward analysis")
    pwg = pw.add_mutually_exclusive_group(required=True)
    pwg.add_argument("--csv")
    pwg.add_argument("--demo", action="store_true")
    pw.add_argument("--symbol", default="BTC-USD")
    pw.add_argument("--train", type=int, default=400)
    pw.add_argument("--test", type=int, default=100)
    pw.add_argument("--step", type=int, default=100)

    # ---- validate ----
    pv = sub.add_parser("validate", help="Validate a YAML config")
    pv.add_argument("--config", required=True)

    # ---- demo ----
    sub.add_parser(
        "demo",
        help="Self-contained end-to-end demo (backtest + HTML report)",
    )

    # ---- dashboard ----
    pd = sub.add_parser("dashboard",
                        help="Run a backtest and stream it to a live HTTP dashboard")
    pdg = pd.add_mutually_exclusive_group()
    pdg.add_argument("--csv")
    pdg.add_argument("--demo", action="store_true")
    pd.add_argument("--symbol", default="BTC-USD")
    pd.add_argument("--port", type=int, default=8765)
    pd.add_argument("--host", default="127.0.0.1")
    pd.add_argument("--no-browser", action="store_true",
                    help="Do not auto-open a browser tab")


# --------------------------- shared loaders ---------------------------

def _load_bars_from_arg(args, default_path: str) -> tuple:
    """Return (bars, symbol_label) for sub-commands that take --csv/--demo."""
    from bot.data.csv_loader import load_csv_bars
    if getattr(args, "demo", False):
        path = default_path
        symbol = args.symbol
    elif getattr(args, "csv", None):
        path = args.csv
        symbol = args.symbol
    else:
        raise SystemExit("error: one of --csv or --demo required")
    if not Path(path).exists():
        raise SystemExit(f"error: data file not found: {path}")
    return load_csv_bars(path), symbol


def _default_strategy(symbol: str):
    from bot.strategies import SupportResistanceRejection
    return SupportResistanceRejection(symbol=symbol)


# --------------------------- sub-commands ----------------------------

def cmd_backtest(args) -> int:
    from bot.backtester import Backtester
    if args.config:
        from bot.config import build_from_config, load_yaml
        cfg = load_yaml(args.config)
        broker, strategy, risk, meta = build_from_config(cfg)
        # Loader to taste — config drives the venue but for offline use we
        # need bars from somewhere. Fall back to bundled sample if no CSV
        # path is supplied in the config.
        csv_path = cfg.get("data_csv") or _bundled_path(meta["symbol"])
        if not Path(csv_path).exists():
            print(f"error: data CSV not found: {csv_path}", file=sys.stderr)
            return 2
        from bot.data.csv_loader import load_csv_bars
        bars = load_csv_bars(csv_path)
        bt = Backtester(strategy, bars, risk=risk,
                        starting_cash=cfg.get("starting_cash", 10_000.0),
                        timeframe=meta["timeframe"], market=meta["market"])
    else:
        bars, symbol = _load_bars_from_arg(args, "data/samples/BTC-USD.csv")
        bt = Backtester(_default_strategy(symbol), bars)
    result = bt.run()
    return _emit_result(result, args)


def cmd_multi(args) -> int:
    from bot.data.csv_loader import load_csv_bars
    from bot.multi_backtester import MultiSymbolBacktester
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    bars: dict = {}
    strategies: dict = {}
    for sym in symbols:
        p = _bundled_path(sym)
        if not Path(p).exists():
            print(f"error: missing sample data for {sym} ({p})", file=sys.stderr)
            return 2
        bars[sym] = load_csv_bars(p)
        strategies[sym] = _default_strategy(sym)
    bt = MultiSymbolBacktester(strategies=strategies, bars=bars)
    result = bt.run()
    return _emit_result(result, args)


def cmd_walkforward(args) -> int:
    from bot.walkforward import walk_forward
    bars, symbol = _load_bars_from_arg(args, "data/samples/BTC-USD.csv")
    def build_strategy(_train_bars):
        return _default_strategy(symbol)
    report = walk_forward(
        bars, build_strategy,
        train_bars=args.train, test_bars=args.test, step=args.step,
    )
    if not report.windows:
        print("Windows: 0 (data too short for the given train/test sizes)")
        return 1
    print(report.summary())
    print(f"Overall robust: {report.is_robust()}")
    return 0


def cmd_validate(args) -> int:
    from bot.config import build_from_config, load_yaml
    try:
        cfg = load_yaml(args.config)
        broker, strategy, risk, meta = build_from_config(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"INVALID: {e}", file=sys.stderr)
        return 1
    print(f"OK: venue={broker.name} strategy={strategy.name} "
          f"symbol={meta['symbol']} timeframe={meta['timeframe']} "
          f"mode={meta['mode']}")
    return 0


def cmd_demo(args) -> int:
    """End-to-end self-contained demo."""
    from bot.backtester import Backtester
    from bot.data.csv_loader import load_csv_bars
    from bot.reporting import render_report
    sample = Path("data/samples/BTC-USD.csv")
    if not sample.exists():
        # Lazily generate if not bundled (handy in fresh checkouts).
        from bot.data.synthetic import generate_bars, write_csv
        write_csv(generate_bars(2000, "1h", seed=1), str(sample))
    bars = load_csv_bars(str(sample))
    bt = Backtester(_default_strategy("BTC-USD"), bars)
    result = bt.run()
    print(result.summary(ascii_chart=True))
    out_html = render_report(result, title="Demo Backtest — BTC-USD",
                             output_path="report.html")
    print(f"\nWrote {out_html}")
    return 0


def cmd_dashboard(args) -> int:
    from bot.backtester import Backtester
    from bot.data.csv_loader import load_csv_bars
    from bot.dashboard import serve_replay
    if args.csv:
        path = args.csv
        symbol = args.symbol
    else:
        path = "data/samples/BTC-USD.csv"
        symbol = args.symbol
    if not Path(path).exists():
        # generate sample on demand
        from bot.data.synthetic import generate_bars, write_csv
        write_csv(generate_bars(2000, "1h", seed=1), path)
    bars = load_csv_bars(path)
    serve_replay(
        strategy_factory=lambda: _default_strategy(symbol),
        bars=bars, host=args.host, port=args.port,
        open_browser=not args.no_browser,
    )
    return 0


# --------------------------- output ----------------------------------

def _emit_result(result, args) -> int:
    if getattr(args, "report", None):
        from bot.reporting import render_report
        p = render_report(result, output_path=args.report)
        print(f"Wrote report: {p}")
    if getattr(args, "equity_csv", None):
        result.export_equity_csv(args.equity_csv)
        print(f"Wrote equity CSV: {args.equity_csv}")
    if getattr(args, "trades_jsonl", None):
        result.export_trades_jsonl(args.trades_jsonl)
        print(f"Wrote trades JSONL: {args.trades_jsonl}")
    if getattr(args, "json", False):
        payload = {
            "starting_equity": result.starting_equity,
            "ending_equity": result.ending_equity,
            "metrics": result.metrics,
            "num_trades": len(result.trades),
        }
        print(json.dumps(payload, default=str, indent=2))
    else:
        # MultiBacktestResult.summary() doesn't take kwargs; single-symbol does.
        try:
            print(result.summary(ascii_chart=True))
        except TypeError:
            print(result.summary())
    return 0


# --------------------------- helpers ---------------------------------

def _bundled_path(symbol: str) -> str:
    """Map a symbol label like 'BTC-USD' or 'BTC/USDT' to a bundled CSV."""
    s = symbol.replace("/", "-").replace(":", "-").upper()
    return f"data/samples/{s}.csv"


# --------------------------- main ------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bot",
        description="Multi-asset trading bot CLI",
    )
    _build_subparsers(p)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    handler = {
        "backtest": cmd_backtest,
        "multi": cmd_multi,
        "walkforward": cmd_walkforward,
        "validate": cmd_validate,
        "demo": cmd_demo,
        "dashboard": cmd_dashboard,
    }[args.cmd]
    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
