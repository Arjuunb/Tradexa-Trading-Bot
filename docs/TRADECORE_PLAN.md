# TradeLogX Nexus — TradeCore Unification Plan (Sprint 4)

*The scoping + migration plan for the DSP's critical-path work: collapsing 4–5
separate trading/simulation engines onto one shared core, proven consistent by
an equivalence-test gate. **This document is a plan — no engine code changes
land with it.** It is grounded in a full read-only audit of the current engines
(file:line references throughout).*

> **Status:** Plan · **Complexity:** XL · **Priority:** P0 (critical path) ·
> **Protect this sprint** — per DSP §"non-negotiable insight". Implementation is
> multi-slice, each behind the equivalence gate defined in §6.

---

## 1. Why this matters

The product asserts "consistent across paper / replay / backtest / live", but
that consistency is **not proven** — it's four independent implementations that
happen to look similar. The audit found the *same* per-trade cost formula
written in **four** files and break-even/partial-TP logic reimplemented in
**four** places, with fees represented three incompatible ways (dollars, R,
bps) and three different default fee rates. The concrete user-facing risk:

> **Live paper charges ZERO fees by default** (`execution/paper_engine.py:38`
> defaults to `PerfectFill`), while **every research backtest charges fees**
> (`strategies/custom.py:670` bakes in `fee=0.0004, slippage=0.0002`). A
> strategy validated in the backtester is systematically **rosier** when run
> live-paper — unless `HUB_FILL_MODEL=realistic` is set. That is a silent
> correctness gap, exactly the kind Sprint 4 exists to close.

Unification is **not** a rewrite. Two shared primitives already exist and are
correct; the work is to route the other engines through them and add the test
that proves they agree.

---

## 2. Current state — five engines, two families

| Engine | File:line | SL/TP source | Fill / fee source | Fee form | Data |
|---|---|---|---|---|---|
| AutoStrategyEngine (live/paper) | `services/auto_engine.py:44` | **TradeManager** | PaperExecutionEngine + fill_model | $ round-trip | live / local `get_bars` |
| PaperExecutionEngine | `execution/paper_engine.py:33` | (n/a — fill layer) | **fill_model** (`PerfectFill` default) | $ | — |
| custom.simulate_strategy | `strategies/custom.py:670` | **TradeManager** | inline `cost_r` | R | historical |
| build_replay | `services/replay.py:439` | inline TP1/BE/TP2 (`:644-680`) | inline `cost_r` (`:763`) | R | historical |
| Backtester (+ PaperBroker) | `bot/backtester.py:135` | inline T3/T4 (`:314-412`) | **PaperBroker** bps (`bot/brokers/paper.py:62`) | bps | `get_bars` / LiveFeed |
| GridBot / GridRunner | `services/grid_engine.py:32` | none (grid has no stops) | inline `fee_pct/100` | % | `get_bars` |
| execution_sim overlay | `services/execution_sim.py:34` | (post-hoc re-pricing) | inline `cost_r` (`:49`) | R | trade list |
| backtest.py CLI | `backtest.py:107` | inline (`:122-131`) | inline (`:133`) | R | CSV |

**Two families that share almost nothing:**
- **Family A** (signal-pipeline): AutoStrategyEngine + PaperExecutionEngine +
  custom.simulate_strategy + build_replay. Fill at signal-bar close / limit.
- **Family B** (event-driven): `bot/backtester.py` Backtester + PaperBroker,
  driving *both* `paper_trading/simulator.run_paper` and the real-time
  `bots/live_runner.py:58` LiveBotRunner. Fill at **next bar open**.

The one genuine piece of cross-mode reuse today: **`TradeManager`**
(`services/trade_manager.py:77`) is shared by exactly two paths — the live
engine (`auto_engine.py:499`) and the research backtester (`custom.py:741`).

---

## 3. The duplicated-logic inventory (what unification deletes)

**3a. Per-trade cost in R** — `cost_pct * entry * 2 / risk`, written 4×:
- `backtest.py:133` · `services/execution_sim.py:49` · `services/replay.py:763`
  · `strategies/custom.py:758` (variant `(entry_cost+cost)*entry/risk`).

**3b. Break-even / partial-TP / trailing** — implemented independently 4×:
- `services/trade_manager.py:97` (the shared, tested one) ·
  `services/replay.py:644-680` (TP1/BE/TP2) · `bot/backtester.py:314-412`
  (T3/T4) · `backtest.py:122-131` (plain stop/TP).

**3c. Fee representation** — three incompatible forms + three default rates:
- dollars (`paper_engine.py:202`), R-multiple (`custom.py:758`,
  `replay.py:763`, `execution_sim.py:49`), bps (`bot/brokers/paper.py:62`).
- rates: fill_model taker 0.04% (`fill_model.py:38`); custom 0.04%+0.02%
  (`custom.py:670`); PaperBroker 0.05%+0.02% (`paper.py:49`); grid 0.04%
  (`grid_engine.py:38`).

**3d. Position sizing** — two models: dollar-off-equity (`bot/backtester.py:257`,
`risk/position_sizing.py:24`) vs pure-R with no equity feedback (custom/replay).

---

## 4. Cross-mode consistency risks (ranked)

| # | Risk | Evidence | Severity |
|---|---|---|---|
| R1 | Live paper = 0 fees; backtest = fees → live looks rosier | `paper_engine.py:38` vs `custom.py:670` | **High** |
| R2 | "R" means 3 different things (gross / net / R-minus-cost) | `paper_engine.py:237`, `backtester.py:449`, `custom.py:758` | **High** |
| R3 | Fill timing differs (next-open vs signal-close/limit) | `paper.py:195` vs `custom.py:711` | High |
| R4 | Same-bar SL+TP tie-break implemented independently | `trade_manager.py:112`, `paper.py:262`, `replay.py:647` | Med |
| R5 | 3 disagreeing "realistic" fee configs (4/5 bps, slips) | §3c | Med |
| R6 | Sizing split — drawdown shrinks size live but not in research backtest | `position_sizing.py:24` vs custom/replay | Med |

---

## 5. Target design — what "TradeCore" is

TradeCore is **not a new engine**. It is the extraction of the four decisions
every engine must make per bar into shared, single-source-of-truth components,
anchored on the two primitives that already exist and are tested:

```
              ┌────────────────── TradeCore (per bar) ──────────────────┐
  strategy →  │  ① fill    → services/fill_model.py  (entry/exit price, │
  signal      │              slippage, maker/taker)   ← already pluggable │
              │  ② manage  → services/trade_manager.py (SL/TP/BE/trail)  │
              │              ← already shared by live + research backtest │
              │  ③ cost    → tradecore/costs.py  (ONE fee→R/$ function)  │  ← NEW, replaces 4 copies
              │  ④ account → tradecore/rmath.py  (ONE definition of R)   │  ← NEW, replaces 3 defs
              └──────────────────────────────────────────────────────────┘
```

- **① and ② already exist** — the work is to make replay (`replay.py`) and
  Backtester (`bot/backtester.py`) *call* `TradeManager`/`fill_model` instead of
  their inline copies (deletes 3b for 3 of 4 engines, fixes R4).
- **③ `tradecore/costs.py`** — one function `cost_r(entry, risk, fee_pct,
  slippage_pct)` + `cost_dollars(...)`; every engine imports it (deletes 3a/3c,
  fixes R1/R5). Single default fee/slippage constants live here.
- **④ `tradecore/rmath.py`** — one canonical `net_r(entry, exit, risk, cost)`;
  every engine reports the same R (fixes R2).

**Explicitly OUT of scope (stay separate):**
- **GridBot** — has no stops and a fundamentally different (grid-level) fill
  model; it only needs to adopt ③ for its fee (small win), not the whole core.
- **Fill *timing*** (R3) — next-open vs signal-close is a *modeling choice*, not
  a bug; TradeCore parameterizes it (`fill_timing="next_open"|"signal_close"`)
  rather than forcing one. The equivalence test pins timing per comparison.

---

## 6. The equivalence gate — build this FIRST, before any engine change

The audit confirmed the critical gap: **no test asserts the engines agree.**
Existing tests are intra-engine or gate-only (`test_phase1_trade_mgmt.py:149`,
`test_parity_and_cache.py:53`, `test_judge_parity.py`, `test_quant_phase.py:112`).

**Deliverable 0 (first slice):** `tests/test_engine_equivalence.py` — run the
*same* strategy over the *same* fixed bar series through each engine with
**identical cost + fill-timing config**, and assert the trade list agrees:
entry price, exit price, exit reason, and net-R within a tight tolerance.

- Start as a **characterization test**: capture today's actual outputs so any
  divergence is visible and intentional. Where engines legitimately differ
  today (R1/R2), assert the *current* numbers and annotate the delta as a known
  gap — never fake agreement.
- As each engine adopts TradeCore, tighten the corresponding assertion from
  "documented delta" to "exact match". The gate goes green **incrementally**.

This test is the contract the rest of Sprint 4 is measured against.

---

## 7. Phased migration (each phase = one PR, gate stays green)

| Phase | Change | Deletes / fixes | Risk |
|---|---|---|---|
| **S4.0** | Characterization gate. **Done for replay** (`tests/test_replay_characterization.py` + `tests/fixtures/replay_snapshot.json`) — pins replay's per-trade output on deterministic synthetic fixtures covering the partial→break-even and stop paths, so S4.4's impact shows up as a reviewable snapshot diff. Verified to fail on a 0.01 R drift. Extending it to a cross-engine comparison remains open (blocked with S4.5 by the packaging split). | — (establishes baseline) | none |
| **S4.1** | Add `tradecore/costs.py` (③) + `tradecore/rmath.py` (④); no callers yet, unit-tested | — | none |
| **S4.2** | Route `custom.py`, `replay.py`, `execution_sim.py`, `backtest.py` cost math → `tradecore.costs` | 3a, R5 | Low (pure fn) |
| **S4.3** | Unify R reporting → `tradecore.rmath` across engines | 3d→R2 | Med |
| **S4.4** | ✅ **Done.** `build_replay` adopts `TradeManager` (inline TP1/BE/TP2 state machine deleted). Mapped exactly: `scale_at_r=be_at_r=TP1_R`, `scale_frac=PARTIAL_FRAC`, `target=tp2`, no trail/time-stop — the blended-R formula is algebraically the one replay computed inline. **Verified byte-identical across 24 fixtures / 88 closed trades.** One intentional semantic change is pinned by a test: on a single bar spanning both the 1R partial and the final target, the runner now closes that bar instead of staying open (the old behaviour was a latent bug). | 3b, R4 | **Med-High** — replay UI parity |
| **S4.5** | 🟡 **Partially done — packaging unblocked (S4.5a), gate built, swap NOT taken.** See the finding below: the remaining swap is **not** behaviour-preserving and needs an explicit product decision. | 3b, R4 | **High** — drives live bot runner |

### S4.5 finding — the Backtester swap is NOT a like-for-like refactor

Unlike replay (a pure state machine, swapped cleanly in S4.4), the event-driven
engine is **broker-routed**, and the two designs disagree structurally:

| | `Backtester._manage_open_trade` | `TradeManager.on_bar` |
|---|---|---|
| who fills SL/TP | **`PaperBroker.on_bar`** (`sl_first`, next-bar-open, bps fees) | returns an exit **price** itself |
| trigger mark | **`bar.close`** (`r_now`) | **`high`/`low`** (intrabar) |
| partial | a **real broker order** (`partial_close`) with its own fee share + trade row | a partial **price**, no order/fees |
| R | dollars (`net_pnl / risk_dollars`) | price-based multiples |

Swapping would move the partial/BE **trigger timing** (close → intrabar) and
lose the broker's fee-accurate partial fills — i.e. it changes numbers on the
path that drives `bots/live_runner.LiveBotRunner`. Forcing it would be a
behaviour change disguised as a refactor, so it is deliberately **not** taken
here. `tests/test_backtester_characterization.py` now pins the engine so that
whenever this is done, the impact is visible.

### ✅ FIXED — the break-even R bug (approved and corrected)

R is now measured against `self._risk_per_unit`, captured **at entry**, so the
break-even move can no longer collapse the denominator. The profitable
remainder in the fixture reports **2.0R** instead of 0.0R. The same fix also
cleared a **second latent effect**: when break-even fired *before* the partial,
`_manage_open_trade` recomputed risk as 0 and returned early, silently
**disabling partial-TP** for the rest of the trade — now covered by its own
regression test. Both suites green (105 root + 920 hub).

### 🐛 The bug as originally found (kept for the record)

After T3b moves the stop to break-even, `planned_sl == entry_price`, so
`risk_dollars = |entry - sl| * qty == 0` and `bot/backtester.py`'s
`net_pnl / risk_dollars if risk_dollars > 0 else 0.0` reports **0.0R for a
profitable remainder** (+$49.02 in the pinned fixture). P&L is correct; only the
R attribution is wrong — it divides by the POST-break-even risk instead of the
trade's ORIGINAL risk. Pinned rather than fixed because this engine drives live
trading: correcting R changes reported live numbers and must be an explicit,
reviewed decision. **Suggested fix when approved:** keep the original
`risk_per_unit` on the trade at entry and divide by that.
| **S4.6** | ✅ **Done (opt-in).** `HUB_UNIFIED_FEES=1` makes live paper charge exactly what the research backtest charges — `DEFAULT_FEE_PCT + DEFAULT_SLIPPAGE_PCT = 0.0006` per side, sourced from `bot.tradecore.costs` so the two cannot drift. **Default OFF**, because enabling it changes live paper P&L and must be a deliberate choice. `HUB_FILL_MODEL=realistic` still wins as an explicit override. Verified: default 0.0 per side vs backtest 0.0006 (the R1 gap); with the flag both are 0.0006. | R1 | **High** — changes live P&L numbers |
| **S4.7** | Tighten equivalence gate to exact-match; make it a required CI gate | proves the sprint | — |

### ✅ RESOLVED in S4.5a — TradeCore now lives in `bot/tradecore/`

The blocker below is fixed. `tradecore` (and `trade_manager`) moved into
**`bot/tradecore/`** — `bot` is the repo-root package the editable install
already maps (`{'bot': '<repo>/bot'}`, and CI runs `pip install -e ".[dev]"`),
so it is importable from *both* the root test suite and `automation-hub/` with
**no new packaging mechanism**. `automation-hub/services/trade_manager.py`
remains as a re-export shim, so all 16 existing import sites keep working.
Verified: `bot/` imports TradeCore with `automation-hub` off `sys.path`; both
suites green (96 root + 920 hub).

### ⚠️ Structural blocker found during S4.3 (now resolved above)

`tradecore` lives in `automation-hub/`, but **Family B (`bot/backtester.py`,
`bot/multi_backtester.py`) is a repo-ROOT package**, and the root-level test
suite imports it *without* `automation-hub` on `sys.path`. Adding a `tradecore`
import there today breaks the root suite (verified, not assumed).

**Consequence:** S4.5 must be preceded by a packaging decision — either move
`tradecore` to the repo root, publish it as a small shared package, or have
Family B keep its own copy behind a pinned equivalence test. This is now a
prerequisite of S4.5, not an implementation detail of it.

Relatedly, Family B's R is **dollar-denominated** (`net_pnl / risk_dollars`,
already net of fees) — genuinely a different quantity from the price-based
`gross_r`/`net_r`, so it must be reconciled deliberately (S4.5/S4.6), never
mechanically swapped. `tests/test_tradecore.py` pins that divergence.

**Sequencing rationale:** cheap, safe, pure-function consolidations first
(S4.1–S4.3) to build confidence and shrink the surface; the two behavior-moving
changes (S4.4 replay, S4.5 Backtester) isolated to their own PRs because each
touches a *user-visible* surface (replay journal UI; the live bot runner). S4.6
is last and loudest — it changes real live-paper P&L, so it ships behind an
explicit flag + changelog, never silently.

---

## 8. Risks & rollback

| Risk | Mitigation |
|---|---|
| Replay UI numbers shift (S4.4) | Gate pins pre/post replay output; ship behind review of a visual diff |
| Live bot runner regresses (S4.5) | `bots/live_runner.py` runs Backtester.step live — add a live-runner smoke test to the gate before touching it |
| Live paper P&L changes (S4.6) | Flag `HUB_UNIFIED_FEES`, default off first release; document the delta; flip default only after a full validation pass |
| Hidden coupling in `custom.py` (used by presets, backtest_lab, judge) | S4.2/S4.3 are pure-function swaps; the existing `test_quant_phase`/`test_judge_parity` suites guard them |
| Scope creep into a rewrite | Hard rule: TradeCore only extracts existing decisions; no new engine, no new strategy semantics |

---

## 9. Definition of Done (Sprint 4)

- [ ] `tests/test_engine_equivalence.py` is a **required CI gate**, asserting
      entry/exit/reason/net-R **exact match** across live-paper, custom backtest,
      replay, and Backtester on a shared fixture (matched cost + fill-timing).
- [ ] `cost_r` / net-R defined in **one** place each; the 4× / 3× duplicates in
      §3a/§3b are deleted.
- [ ] Replay and Backtester manage SL/TP via `TradeManager` (only the shared
      implementation remains, plus grid which is intentionally exempt).
- [ ] Live-paper fee behavior is consistent with the research backtest (or
      explicitly, documentedly configurable) — R1 closed.
- [ ] Full backend suite green; no user-visible regression in the paper MVP.

---

## 10. What this plan deliberately does NOT do

- No live-exchange execution (that is Sprint 9, gated).
- No change to strategy logic, scoring, or the AI decision path.
- No grid-engine rewrite (adopts only the shared cost fn).
- No database/schema change.

The end state: **one core, four call-sites, one proof.** Every mode fills,
manages, costs, and accounts for a trade the same way — and a CI gate fails the
build if they ever drift again.
