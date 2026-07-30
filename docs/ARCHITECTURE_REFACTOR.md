# Clean Architecture consolidation

Living plan for moving Tradexa onto a Clean Architecture footing **without
changing behaviour**. Updated as each phase lands.

## Why this is a consolidation and not a rewrite

The brief asked for a refactor into a fresh `tradexa/` tree. An audit of the
codebase before starting changed the shape of that work, and the finding is
worth stating plainly, because it determines the whole plan:

**the dependency arrows are already mostly correct.**

| Check | Result |
| --- | --- |
| `services/` importing FastAPI | **0 files** |
| `bot/` (engine) importing FastAPI, sqlite3, requests | **0 files** |
| `bot/` importing ccxt | 1 file |
| `services/` importing sqlite3 | 1 file |
| Existing ABC ports | `bot/brokers/base.py`, `bot/strategies/base.py` |
| Existing typed domain models | `bot/types.py` — 9 types |
| Existing unified trade core | `bot/tradecore/` (costs, rmath, trade_manager) |

The engine does not import the web framework. Strategies and brokers already
sit behind abstract base classes. The cost and R-multiple maths was unified
into one module in an earlier sprint. This is not a big ball of mud that needs
demolishing — it is a working system with real gaps.

Moving 429 Python files into a new namespace would break every import, the
Dockerfile, the Render deploy and 1376 passing tests, in exchange for a tidier
directory listing. That trade is not worth making on a system that is live.

So `tradexa/` grows **additively**, and callers migrate deliberately, one
seam at a time, each with tests proving behaviour is unchanged.

### The genuine gaps

1. **One custom exception in the entire codebase** (`BrokerError`). Everything
   else raised bare `Exception` or was swallowed by `except Exception`.
2. **No event bus.** Modules call each other directly.
3. **Ports missing** for RiskManager, PortfolioManager, MarketDataProvider,
   EventBus, Logger, Storage, Clock.
4. **Domain concepts with no type** — closed trades, execution reports, risk
   verdicts, portfolio snapshots all travel as bare dictionaries.
5. **Risk logic is spread** across services and execution rather than owned.
6. **Config is env-var only.** No YAML/JSON layer.
7. **No structured logging.**

---

## Phases

| # | Phase | Risk | Status |
| --- | --- | --- | --- |
| 1 | Foundation — models, exceptions, ports, event vocabulary | none (additive) | **done** |
| 2 | Event bus + structured logging | low (publish-only) | **done** |
| 3 | Risk engine behind `RiskManager` | medium | next |
| 4 | Portfolio engine behind `PortfolioManager` | medium | planned |
| 5 | Execution engine consolidation | medium | planned |
| 6 | Strategy plugin registry | low | planned |
| 7 | Config: YAML/JSON + env precedence | low | planned |
| 8 | Migrate callers, deprecate old paths | high | planned |

A phase is not started until the previous one is merged with both suites green.

---

## Phase 1 — Foundation (complete)

**What changed.** Added `tradexa/core/` with four modules and nothing else:

- `models/` — re-exports the nine canonical types from `bot.types`, and adds
  the seven that had no type: `Candle`, `Tick`, `Trade`, `ExecutionReport`,
  `RiskAssessment`, `StrategyResult`, `PortfolioSnapshot`.
- `exceptions/` — 16 exceptions under one root, each carrying structured
  `context` and a `retryable` flag.
- `interfaces/` — 12 ports as `typing.Protocol`.
- `events/` — 13 frozen event types. Vocabulary only; the bus is Phase 2.

Plus `tests/test_core_architecture.py`, 36 tests.

**Why, on the decisions that were not obvious.**

*Models re-export rather than redefine.* Declaring a second `Order` in
`tradexa` would create two types with the same name and no conversion between
them. Every seam touching both would need a translation layer that nobody
keeps in step. `test_canonical_types_are_reexported_not_redefined` asserts
identity (`is`), so a future edit that forks a type fails the build.

*Ports are Protocols, not ABCs.* `bot.brokers.base.Broker` is an ABC with live
subclasses. Requiring those to also inherit from a `tradexa` base would mean
editing production code to satisfy a refactor. Protocols are structural — the
existing classes already conform, with no import and no edit. Tests assert
this.

*Exceptions expose `retryable` on the type.* Retry policy is the most
consequential branch in a live trading loop: retrying a permanent failure burns
the rate limit; aborting a transient one drops a fill. Making it a property of
the type means a handler cannot get it wrong by inspecting a message string.

*`RiskAssessment` carries the approved size.* Approval and sizing are one
decision. Returning a bare bool is what forces sizing to be recomputed
elsewhere and drift from the rule that authorised it.

*`StrategyResult` models "no signal" with a reason.* A strategy that declines
to trade is doing its job, and "why isn't it trading?" is otherwise
unanswerable after the fact.

*Events are past-tense and frozen.* An event states that something happened; a
command requests that something should. Mixing them turns a bus into a call
graph with extra steps. Frozen because several subscribers hold the same
instance.

**Files added.**

```
tradexa/__init__.py
tradexa/core/__init__.py
tradexa/core/models/__init__.py
tradexa/core/exceptions/__init__.py
tradexa/core/interfaces/__init__.py
tradexa/core/events/__init__.py
tests/test_core_architecture.py
docs/ARCHITECTURE_REFACTOR.md
```

**Files modified.** None.

**Risks introduced.** None to runtime behaviour. No existing file was touched,
and `test_nothing_in_the_existing_system_imports_tradexa_yet` asserts that no
production module depends on the new package — so nothing can regress through
it until a later phase migrates a caller deliberately.

The one ongoing risk is drift: a new package that nobody imports can rot.
Phase 2 begins using it immediately, which is the mitigation.

**Verification.**

| Suite | Before | After |
| --- | --- | --- |
| Root engine (`tests/`) | 128 passed | **164 passed** (+36 new) |
| Backend (`automation-hub/tests/`) | 1376 passed | **1376 passed** |

No existing test was modified, skipped or deleted.

### The dependency rule is enforced, not documented

`test_core_never_imports_infrastructure` walks every module under
`tradexa.core` and fails if any imports FastAPI, sqlite3, ccxt, requests,
redis, websockets or similar. It reads the **AST**, not the source text, so
prose mentioning a banned name cannot fail it and a real import cannot hide
from it.

A companion test checks parameter and return **annotations** for infrastructure
types, catching an interface that relocates coupling into a signature rather
than removing it.

---

---

## Phase 2 — Event bus + structured logging (complete)

**What changed.** Added `tradexa/infrastructure/` with two implementations, and
wired **one** production seam end to end.

- `infrastructure/events/` — `InMemoryEventBus` (the `EventBus` port),
  `NullEventBus`, and a process-wide `default_bus()`.
- `infrastructure/logging/` — `StructuredLogger` (the `Logger` port),
  `NullLogger`, `get_logger()`.
- `services/auto_engine.py` publishes `MarketDataReceived` from `_process_bar`.

**Why these decisions.**

*The bus is synchronous.* An async or cross-process bus introduces ordering,
backpressure and delivery-guarantee problems worse than the coupling it
removes. A synchronous bus is a decoupled function call: the publisher does not
know who listens, but still knows the work is done when `publish` returns.

*A failing subscriber cannot reach the publisher.* The single most important
property here. If a notifier raises while handling `OrderFilled`, the fill must
still be recorded. A bus that propagates handler failures is strictly worse
than a direct call, because it fails a publisher on behalf of code the
publisher never chose to depend on. Isolated is not ignored — errors go to an
error sink and are counted.

*Publish depth is bounded.* A handler that publishes an event leading back to
itself is reported as a cycle rather than arriving as a `RecursionError`
thousands of frames from the cause.

*Logging is event-name-plus-fields, never a formatted sentence.*
`f"{sym}: fetch failed ({e})"` cannot answer "how many fetch failures on
BTCUSDT this hour?" without a regex that breaks on the next wording change.

*`event` is positional-only.* A test caught that `**context` could never carry
a key named `event` — Python raises `TypeError` before the collision handling
runs, so any caller splatting a context dict containing that key would crash
rather than log. The `/` fixes it at the signature.

*The engine seam is publish-only.* `_process_bar` publishes and never
subscribes or reads a result, so no trading control flow depends on whether
anyone is listening. The call is additionally wrapped: the bus isolates
subscriber errors, and the guard covers constructing the event itself failing.
Telemetry must never be able to stop a bar being traded.

**Files added.**

```
tradexa/infrastructure/__init__.py
tradexa/infrastructure/events/__init__.py
tradexa/infrastructure/logging/__init__.py
tests/test_event_bus.py
automation-hub/tests/test_engine_events.py
```

**Files modified.**

```
automation-hub/services/auto_engine.py   publish MarketDataReceived (+ guarded import)
automation-hub/conftest.py               repo root APPENDED to sys.path
tradexa/core/interfaces/__init__.py      Logger port: event is positional-only
tests/test_core_architecture.py          allowlist replaces the blanket ban
```

**Risks introduced.**

1. *A production file now imports `tradexa`.* Mitigated by a guarded import —
   a deployment shipping only `automation-hub` still starts, with events going
   nowhere rather than the engine failing to import.
2. *Per-bar overhead.* One dict lookup and a counter when nothing subscribes.
   Bars arrive minutes apart.
3. *`conftest.py` path change.* The repo root is **appended**, never inserted:
   the root also contains a `data/` package, and giving it priority would
   shadow the app's `data.ledger` with different code of the same name — an
   import that succeeds and resolves wrongly is the worst kind of path bug.

**Verification.**

| Suite | Phase 1 | Phase 2 |
| --- | --- | --- |
| Root (`tests/`) | 164 passed | **200 passed** (+36) |
| Backend (`automation-hub/tests/`) | 1376 passed | **1381 passed** (+5) |

The five new backend tests run against the **real** engine — real ledger, real
pipeline, real strategy — not a mock, including one asserting that a subscriber
raising mid-delivery does not stop the bar being recorded.

### The Phase 1 guard did its job

`test_nothing_in_the_existing_system_imports_tradexa_yet` failed the moment
Phase 2 wired the engine. That is the test working. It is now an **allowlist**:
each deliberate consumer is listed with its rationale, an unlisted import fails
the build, and a companion test rejects stale entries so a reverted migration
cannot leave a permanent exemption behind.

---

## Phase 3 — Risk engine behind `RiskManager` (next)

Risk logic currently lives across `services/signal_pipeline.py`,
`services/controls.py` and the engine itself. Phase 3 gives it one owner
implementing the `RiskManager` port, returning `RiskAssessment` — approval and
size as one decision.

Behaviour must not change: the existing rules, thresholds and rejection
reasons are the specification, and characterization tests come first so any
drift is caught by a test written before the move.

---

## Phase 3c — The event backbone

Extends the phase-2 bus into the communication backbone: full envelope, 22
events, registry, dispatcher, publisher, subscriber, priorities, retry,
metrics, async delivery and replay.

**The envelope.** Every event now carries `timestamp` (aliasing the original
`occurred_at`), `event_id`, `source`, `correlation_id`, `metadata` and
`payload`.

`correlation_id` is the field that earns its keep. One bar arriving produces a
signal, a risk check, an order and a fill — five events across four modules.
Without a shared id, reconstructing that chain from a log means matching on
symbol and timestamp and hoping two symbols did not fire in the same second.
With one, the chain is a filter.

`payload` is a **derived property**, not a stored dict. Storing it would put
the same data twice on one frozen object, and the copy would drift the first
time an event was constructed by hand.

**One collision resolved.** `MarketDataReceived.source` meant the *data*
provenance ("live (ccxt)", "bundled sample"); the envelope needs `source` for
the publishing module. The field is now `data_source`. The distinction matters:
a live-mode engine served bundled data will never see a new candle, and that
failure is invisible unless the data's provenance travels beside the
publisher's identity.

**Why the pieces are separate.**

| Piece | Why it is its own thing |
| --- | --- |
| `EventRegistry` | Replay reads names from a journal; without a registry those are strings with no way back to a class |
| `EventDispatcher` | Delivery policy — priority, retry, metrics, isolation — testable without a publisher and swappable without touching either side |
| `EventBus` | The seam callers hold |
| `EventPublisher` | Stamps source and correlation once per module rather than at every call, so they cannot drift |
| `EventSubscriber` | Attach and detach are symmetric by construction; a scattering of manual subscribe calls is not |

**Priorities** are named constants (`CRITICAL` … `BACKGROUND`) because
registration should read as intent. Equal priorities keep registration order
via a monotonic tiebreaker — without it, sorting is unstable and two handlers
that must run in a fixed order would swap between runs.

**Retries default to zero.** Retrying a handler with side effects duplicates
them, so opting in is a decision the subscriber makes knowing whether its work
is idempotent.

**Async** handlers are awaited by `publish_async`, one at a time rather than
gathered — priority is an ordering promise, and gathering would break it the
moment two async handlers had different priorities. A coroutine handler reached
by the *sync* `publish` is reported as an error rather than silently dropped: a
coroutine created and never awaited leaks and warns.

**Handler failures are republished as `ErrorOccurred`**, so an error monitor is
an ordinary subscriber rather than a special case wired into every publisher.
Guarded against recursion — a failing `ErrorOccurred` handler must not publish
another.

**Replay** records at `BACKGROUND` priority so it can never delay or reorder
real work, and is bounded (an unbounded recorder on a long-running bot is a
memory leak with a helpful name). Replayed events are marked
`metadata["replayed"] = True` and keep their **original** id and timestamp —
keeping the id is what lets a replayed event be matched against the log line
the live one wrote. Serialisation is best-effort and flags lossy fields: a
journal that refused anything it could not perfectly round-trip would record
nothing on the events most worth having.

**Files added.** `tradexa/infrastructure/events/{bus,replay}.py`,
`tests/test_event_backbone.py` (73 tests).

**Files modified.** `tradexa/core/events/__init__.py` (envelope + 9 new
events), `tradexa/infrastructure/events/__init__.py` (re-export),
`automation-hub/services/auto_engine.py` (renamed field at the one call site).

**Risks.** The `data_source` rename touches one production call site, covered
by the existing engine-event tests. No trading control flow changed: the engine
still only publishes, never subscribes, and never reads a result back.

**Verification.** Root suite 324 → **397** passed. Backend **1392** passed,
unchanged. Every phase-2 API — `subscribe`, `publish`, `clear`, `default_bus`,
`published_count`, `handler_error_count` — still works with identical
behaviour, asserted by a backwards-compatibility test.

---

## Phase 4 — Portfolio Engine (`tradexa/portfolio/`)

One view of capital across every broker and exchange, computed independently of
the execution engine.

**Thirteen figures, per venue and in aggregate.** Balance, equity, buying power,
margin (used, free, level), exposure (gross, net, % of equity, by symbol, by
venue), unrealised P&L, realised P&L, daily return, monthly return, win rate,
expectancy, Sharpe ratio, maximum drawdown.

**Why it cannot live in the execution engine.** Execution knows how to place an
order at one venue. "How much do I have, and how exposed am I?" spans all of
them — and one symbol held on two exchanges is *one* exposure, which no single
execution engine can compute. Left inside them, a second broker means a second
copy of the arithmetic, and two copies of a Sharpe ratio drift. Here the venues
are data: one and nine take the same path, and adding an exchange means adding a
`VenueSnapshot`, not touching any calculation.

**The arithmetic is reused, not restated.** Drawdown, Sharpe and expectancy come
from `bot.metrics`, which the backtester already uses. A portfolio page
disagreeing with the backtest report about the same account's Sharpe is worse
than either number being absent. What is genuinely new: calendar-window returns,
daily-close resampling, and multi-venue aggregation.

**Unavailable is a value.** A missing mark, an unreachable venue, a currency
with no FX rate — each yields `None` plus a note naming what is missing, never a
zero. A dashboard that cannot tell "flat" from "unknown" reports the second as
the first at exactly the wrong moment. Two lists travel with the figures:
`notes` (what is missing now — drives `available`) and `basis` (how the figures
are derived). Folding them together made `available` false on every call, which
is a warning nobody reads.

**Files added.** `tradexa/portfolio/{snapshots,metrics,engine}.py`,
`automation-hub/services/portfolio_view.py` (the read-only adapter),
`tests/test_portfolio_engine.py` (43), `automation-hub/tests/test_portfolio_view.py`
(30), `tests/test_packaging.py` (4).

**Files modified.** `pyproject.toml` (see below), `routers/paper.py`
(`/portfolio/snapshot`, `/portfolio/venues`), `services/signal_pipeline.py`
(loud warning when the risk engine is absent),
`tests/test_core_architecture.py` (allowlist entry).

### The packaging bug this phase uncovered

`pyproject.toml` listed only `bot*` under `packages.find`. The Dockerfile runs
`pip install -e .` and starts uvicorn from `automation-hub/`, where the repo root
is **not** on `sys.path` — so in the deployed container every `import tradexa...`
failed:

| | consequence in production |
|---|---|
| `tradexa.risk` | the Risk Engine veto was never applied — `risk_engine = None` |
| `tradexa.risk.sizing` | fell back to its inline copy |
| `tradexa.infrastructure.events` | engine events not published |

Nothing surfaced. The guarded imports degrade quietly, which is right for
resilience and exactly wrong for noticing. And the full suite passed, because
`automation-hub/conftest.py` appends the repo root to `sys.path` — so those
imports resolved under pytest and *only* under pytest.

Fixed by `include = ["bot*", "tradexa*"]`. Guarded three ways: a test asserting
every runtime package is in the install list, a test that walks the backend's
AST and fails on any repo-root import the build does not install, and a boot
warning naming the fix if the risk engine is ever absent again.

The general lesson: **a test suite that manipulates the import path is testing a
different program from the one that deploys.**

**Risks.** The portfolio endpoints' import is deliberately unguarded — if
`tradexa` were missing they fail loudly rather than answering 200 with an empty
portfolio, which is how the veto went absent for a release. The blast radius is
those two endpoints (the import is inside the handler, so boot is unaffected).

**Verification.** Root 461 → **508** passed. Backend 1416 → **1465** passed.
Confirmed the deployed import path directly: `cd /tmp && python -c "import
tradexa.risk"` now resolves, and `pipeline.risk_engine` is a live `RiskEngine`
in the running app rather than `None`.
