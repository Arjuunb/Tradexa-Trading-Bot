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
| 2 | Event bus + structured logging | low (opt-in) | next |
| 3 | Risk engine behind `RiskManager` | medium | planned |
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

## Phase 2 — Event bus + structured logging (next)

Planned scope:

- `tradexa/infrastructure/events/bus.py` — synchronous in-process bus
  implementing the `EventBus` port. A failing subscriber must not abort the
  publisher; handler errors are isolated and reported out of band.
- `tradexa/infrastructure/logging/` — a `Logger` implementation emitting
  timestamp, module, event, severity, duration and context as structured
  records.
- Wire both into **one** seam end to end (the signal pipeline is the
  candidate) so the machinery is proven in production use rather than only in
  tests, before anything else adopts it.

Explicitly out of scope for Phase 2: converting existing direct calls to events
wholesale. Each conversion is a behaviour risk and gets its own change.
