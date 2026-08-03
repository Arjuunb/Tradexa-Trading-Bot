# Architecture Audit — TradeLogX Nexus

Findings from a direct inspection of the running codebase. Every claim here was
measured or executed, not inferred; where I could not verify something I say so.

**Scale:** 36,243 lines of backend Python across 207 files, 17,449 lines of
frontend TypeScript across 102 files, 497 documented API paths (224 under
`/api/v1`).

---

## 1. Unified data architecture — mostly already true

**Finding: the architecture is already unified.** `data/market_data.get_bars()`
is the single canonical entry point, with **49 call sites** covering every module
the sprint spec lists:

| Module | Reaches `get_bars` via |
|---|---|
| Dashboard | `dashboard/overview.py`, `dashboard/widgets.py` |
| Paper Trading | `routers/paper.py`, `paper_trading/simulator.py` |
| Replay | `services/replay.py` |
| Backtesting | `services/backtest_lab.py`, `services/spec_runner.py` |
| AI Strategy Agent | `routers/ai.py` |
| Decision Engine | `services/auto_engine.py`, `services/mtf_engine.py` |
| Analytics | `routers/analytics.py` (14 call sites) |
| Risk | `services/risk_engine.py` |
| Journal / Scanner / Evolution | `services/{scanner,evolution,context_brain}.py` |

There are no competing pipelines. `live_data.py`, `historical.py`,
`yahoo_bars.py` and `ws_feed.py` are *rungs beneath* `get_bars`, not rivals to
it. Two pages cannot disagree about a price because they resolve through the
same function with the same cache.

**The real violation was the bottom of the ladder.** `get_bars` resolves:

```
Yahoo (non-crypto) → local cache of real candles → live ccxt
                   → bundled CSV sample → deterministic synthetic
```

That last rung returns candles from a seeded PRNG. Correct for a test suite,
indefensible in a product people trade from: a production deploy that lost its
feed would keep drawing confident-looking charts out of a random number
generator, with nothing on screen to say so.

A guard already existed — `HUB_REQUIRE_REAL_DATA` — and **was set in no
production configuration at all**. Verified by grep across `Dockerfile`,
`render.yaml`, `deploy/k8s/`, and `deploy/docker/`.

**Fixed.** The flag is now set in all four production configs, with
`tests/test_no_synthetic_in_production.py` failing the build if any of them
drops it. The failure mode it prevents is invisible by construction, so a
reviewer would never notice its absence — it has to be checked mechanically.

**Verified safe before enabling.** All 141 parameterless GET endpoints were
probed with the guard on and no market-data network reachable:
**138 × 200, 3 × 422** (missing query params), **zero 5xx, zero exceptions**.
The app already degrades gracefully to empty results; it was the *silent
fabrication* that was wrong, not the error handling.

### Open gap: cached data is trusted by provenance-free label

`_from_local_store` returns anything in the historical store as
`"local store (real)"` regardless of how it got there. The test suite's
`conftest.py` seeds that store with generated bars — which is how the first
version of my guard test failed. In production the store is only written by the
real Binance sync path, so this is not currently exploitable, but the label is a
claim the code does not check.

**Recommended:** stamp a `source` column on ingest and have `_from_local_store`
refuse rows not marked real when the guard is on. Small change, removes a class
of silent contamination. Not done — flagged rather than fixed.

### Note: replay "demo" mode

`services/replay.py:479` calls `generate_bars` directly, bypassing the ladder.
It is gated behind an explicit `source == "demo"` selection, so it is a user
choice rather than a silent fallback. Left as-is deliberately; if the spec's
"no synthetic candles in production" is meant absolutely, this is the one
remaining place to remove, and it is a two-line change.

---

## 2. The V2 modules in the spec do not exist

The sprint spec repeatedly refers to **Paper Trading V2**, **Market Data V2**
and **Core Engine V2** as existing systems to be wired together, and asks for
"legacy engine vs Core Engine V2 shadow decision" comparison in the Decision
Archive.

I searched the entire repository. **No module, router, service or frontend
component by any of those names exists.** The closest analogues are:

| Spec name | Nearest existing thing |
|---|---|
| Market Data V2 | `data/market_data.py` + its four backing sources |
| Paper Trading V2 | `paper_trading/simulator.py`, `routers/paper.py`, `execution/paper_engine.py` |
| Core Engine V2 | `services/auto_engine.py` + `services/signal_pipeline.py` |

This materially changes several sections. §8's "compare legacy engine decision
vs Core Engine V2 shadow decision" cannot be built as described, because there
is no second engine to shadow with. It would first have to be written — that is
a large project in itself, not a polish task.

**This needs a decision from you** before §4, §8 and parts of §2 can proceed:
either those V2 systems exist somewhere I cannot see (a branch, another repo),
or they are aspirational names and the work is "build them", not "connect them".

---

## 3. What is genuinely strong already

Worth recording, because the spec's framing ("feature-rich prototype")
undersells parts of it:

- **Error handling.** 141 endpoints returned zero 5xx with their data source
  removed entirely. That is better than most production systems.
- **Fail-closed data sources.** `yahoo_bars.py` and `historical.py` both return
  explicit unavailability rather than fabricating. Only the legacy
  `market_data.py` ladder had the synthetic rung.
- **Provenance already reaches the UI.** `data_source` is surfaced in
  `HeaderControls`, `TickerBar`, `ControlBar`, `WhyNoTrades` and
  `CustomBuilder`. The plumbing for "show the user where this number came from"
  exists; it needs extending, not inventing.
- **Risk engine has real veto authority.** Every rejection funnels through one
  `reject()` in `signal_pipeline.py` — which is why instrumenting it took one
  line.

---

## 4. Weaknesses, ranked by risk

| # | Weakness | Risk | Status |
|---|---|---|---|
| 1 | Synthetic candles reachable in production | **Critical** — fabricated prices on a trading screen | **Fixed** |
| 2 | Local cache trusts unverified provenance | High — silent contamination path | Flagged |
| 3 | V2 systems referenced but absent | High — blocks §4, §8 as specified | Needs your decision |
| 4 | Web tier cannot scale (SQLite account store) | High | Documented, [PRODUCTION.md](PRODUCTION.md#scaling-the-web-tier) |
| 5 | `PLATFORM_STATS` on the marketing footer is placeholder | Medium — public-facing fake numbers | Flagged, pre-existing |
| 6 | `/status` page not wired to real monitoring | Medium | Flagged, pre-existing |
| 7 | 49 `get_bars` call sites, most with local imports | Low — works, but makes the seam hard to see | Cosmetic |

---

## 5. Scope reality

Sections §2–§12 of the sprint spec were **not implemented**. That is not an
omission by oversight — it is a statement about size. §3 alone (drawing tools,
measure tool, price ruler, replay scrubbing, fullscreen, SMC structure overlays
driven by backend calculations) is a professional charting product. §4 asks for
a broker simulator spanning six asset classes with partial fills, funding and
margin. §5 is a natural-language strategy compiler with an approval workflow.
Each is weeks of work for a team, not hours.

What I did instead was the thing that had to happen first and that everything
else depends on: establish that the data layer is unified, prove it, and stop
it lying. There is no point polishing an analytics page whose numbers may come
from a PRNG.

Suggested order for the remainder, by dependency:

1. **Decide the V2 question** (blocks §4, §8).
2. **§6 Risk Manager** — the engine already has veto authority and one
   choke point; surfacing its state is mostly UI over existing data.
3. **§2 Decision Engine transparency** — `signal_pipeline.reject()` already
   records stage and reason for every decision; the data exists, it needs a view.
4. **§7 Analytics** — real trade records already exist in the journal.
5. **§8 Decision Archive** — minus the V2 comparison.
6. **§4 Paper Trading V2** — largest backend piece.
7. **§3 Professional chart** — largest frontend piece.
8. **§5 AI Strategy Agent workflow.**
9. **§9–§11 polish, performance, production readiness** — last, once the
   surface stops moving.

§12 (testing) and §13 (deliverables) should run continuously rather than as a
final phase.
