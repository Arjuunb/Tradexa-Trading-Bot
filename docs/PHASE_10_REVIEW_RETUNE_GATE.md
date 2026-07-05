# Phase 10 — Paper Results Review & Strategy Retune Gate

Review the real paper-trading evidence collected in Phase 9 and decide a verdict.
**Live trading stays locked. No auto-retune from small samples. No faked
results.**

---

## Review inputs (all real, read on demand)

| Input | Source |
|---|---|
| Paper Validation verdict | `GET /validation/paper` + panel on Strategy Proof |
| Daily validation report + trend | `GET /validation/daily-report` |
| Strategy Proof metrics | `GET /strategy/performance`, `/strategy/health`, `/lab/walk-forward` |
| Skipped-trade logs + categories | `GET /skipped/trades`, `/skipped/summary` |
| Decision Journal | `GET /journal/trades`, `/journal/{id}` |
| Bot Health history | `GET /health/bot` |
| Safety Center | `GET /safety/live-readiness` |

## Sample-size decision rule

| Closed paper trades | Action |
|---|---|
| **< 30** | Insufficient sample — **continue paper validation**. No retune except a critical infrastructure bug. |
| **30–49** | Early review only — observe; do not change strategy rules. |
| **50+** | Evidence-level review — a retune search may run and produce a *shadow*; promotion still requires the shadow to beat live on its own sample **and** a human decision. |

## Strategy Retune Gate (enforced in code)

`services/retune_gate.py` + `GET /retune/gate` + `POST /retune/run`:

- `POST /retune/run` **refuses** below 30 closed paper trades (`ran: false,
  blocked: true`) — the strategy can't be retuned from a small sample.
- A `critical_bug=true` override is the **only** bypass (logged as a warning);
  even then, **promotion is never allowed** by the override.
- At 50+ trades the search may run and auto-start a **shadow** audition; the
  existing shadow mechanism only reports `promote` once the shadow **and** live
  each have 20+ closed trades — and promotion is still manual.
- The active strategy is **never replaced automatically**.

## Retune → shadow → promote flow (existing, unchanged)

1. `POST /retune/run` (gated) → grid search on real candles (train/test split).
2. A winning candidate **auto-starts as a shadow** (`/shadow/report`) — it runs
   in parallel, it does **not** replace the active strategy.
3. Compare old vs new in paper mode until both have enough trades.
4. Promotion requires evidence **and** an explicit human decision.

## Verdict options

`continue paper validation` · `pause strategy` · `retune (shadow only)` ·
`fix infrastructure bug` · `prepare human live pre-flight (only if eligible)`.

## This review's verdict (run 2026-07-05, current stored data)

- **Sample size:** 0 closed paper trades (no validation run has accumulated
  trades in this environment; the live deploy is where real trades accrue).
- **Metrics:** none yet (0 trades) — not fabricated.
- **Best/worst symbol / strategy / timeframe:** none yet.
- **Skips:** present and categorised; trend `not-enough-history`.
- **Safety:** `live_allowed=false`, `hard_locked=true`.
- **Retune gate:** `insufficient-sample` — retune not allowed, promotion not
  allowed.
- **Verdict:** **continue paper validation.** No retune. Not eligible for live
  pre-flight.

> Re-run this review after the deploy accumulates 30+ (ideally 50+) closed
> paper trades. The numbers above will populate from real trades — never invent
> them.

## Live trading

🔒 **Locked throughout.** Nothing in this phase enables live trading. Eligibility
for a *human* pre-flight requires sample size **and** proven edge **and** all
safety guards — and even then authorises only a review, never an auto-unlock.

## Next recommended phase

**Phase 11 — human live pre-flight design** (only once validation is eligible
with 50+ trades, stable/improving trend, and green safety): broker connection
check, tiny fixed size, dry-run order path, second explicit human confirmation;
live still defaults to locked and every guard enforced.
