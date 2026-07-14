# Explainable Trading — per-cycle Decision Reports

**The bot never places or skips a trade silently.** Every analysis cycle —
every closed candle on every symbol, including the ones where nothing happens —
produces a complete Decision Report, stored and browsable on the dashboard's
**Decisions** page (`GET /engine/cycles`, `GET /engine/cycles/{id}`).

## What every report contains

| Section | Contents |
|---|---|
| Header | symbol, time, timeframe, current price |
| **Market analysis** (`services/market_analysis.py`) | bias (Bullish/Bearish/Neutral), EMA8/EMA33 positions + trend strength, HH/HL–LH/LL swings, structure (trending / consolidation / BOS / CHoCH), nearest demand & supply zones with distances, major/minor S/R levels, volume vs 20-bar average, volatility (ATR%), liquidity (equal highs/lows, sweep detection), last-candle pattern |
| **Strategy checklist** | 8 rules, each PASS / FAIL / **N/A** with a one-line explanation: EMA alignment, structure confirmed, zone valid, rejection candle, RR ≥ 2.0, no major level ahead, volume confirmation, session allowed |
| **Confidence score** | five categories ×20 (Trend, Structure, Supply/Demand, Volume, Risk) → /100; ≥80 strong, 65–79 watchlist, <65 skip-quality. The Decision Brain's own gate score is shown alongside as `engine_score` |
| **Decision** | BUY / SELL / WAIT / SKIP + the real reasons (brain conviction, quality-gate verdict, risk-gate stage, ❌ failed rules) |
| **Recommendation** | what would make the setup tradeable ("wait for a pullback into the zone", "wait for volume confirmation", …) |

The report **explains** the engine — it never forms a parallel opinion. A SKIP
always lists the exact gate and failed rules; a WAIT explains why no setup
qualified. Analysis needs ≥40 bars; below that it says so instead of guessing.

## Trade lifecycle & AI Coach

- Managed positions track **MFE/MAE** (max profit / max drawdown in R) bar by
  bar; both are recorded in the journal's exit section (`max_profit_r`,
  `max_drawdown_r`) — honest `"not tracked"` for positions adopted without
  management state.
- Every completed trade gets an **AI Coach** debrief in its review
  (`review.coach`): strengths and weaknesses composed from the *actual entry
  reads recorded at entry*, one lesson, and a letter rating (A+…F). No invented
  insight — every line traces to a recorded read or the real outcome.

## Storage & honesty

Reports live in `HUB_CYCLES_DB` (default `HUB_DATA_DIR/cycles.db`), pruned to
the newest ~5000 cycles so a 5m × 3-symbol engine runs forever on a small disk.
Screenshots are not captured (no rendering backend) — stated here rather than
faked. Everything else in a report is computed from real bars and real gate
outcomes at the moment of the decision.
