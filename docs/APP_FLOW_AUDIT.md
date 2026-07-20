# TradeLogX Nexus — Application Flow Audit & Refactoring

*Audited 2026-07 · covers the React dashboard (`automation-hub-dashboard`), the FastAPI backend (`automation-hub`), and how the 29 pages compose into one platform. The UI/design language was **not** redesigned — this is an information-architecture refactor.*

---

## 1. Scores

| Dimension | Score | Rationale |
|---|---|---|
| Architecture | **7.5/10** | Clean split (lazy pages, hash routing, typed API layer, shared polling cache). Was a flat 20-item nav of organically-grown pages; now grouped by lifecycle. Backend is honest-data-first with real tests (850 passing). |
| UX | **6.5 → 8/10** | Individual pages are strong; the *collection* lacked hierarchy — three strategy pages, two paper-trading pages and four memory-ish pages sat as siblings with no signposting. Fixed by grouping + dedupe + cross-links. |
| Trading workflow | **7 → 8.5/10** | All lifecycle stages exist (build → observe → replay → backtest → live-gate). They were not ordered as a journey; now the sidebar *is* the journey. Optimization Lab does not exist yet (see roadmap). |
| Developer workflow | **8/10** | Bot Health, Logs, Developer mode in the terminal, Decision Reports, `/health` + `/version`, watchdog. Missing: in-app config diff/audit trail, log search by request id. |
| AI workflow | **7.5/10** | AI Intelligence (pattern/weakness detection), AI Assistant (grounded Q&A), Memory (per-trade long-term memory + coaching), Evolution, Decision Archive. Missing: closing the loop — one-click "apply AI suggestion to strategy/risk settings". |
| Scalability | **7/10** | Code-split pages, shared pollers, Supabase durability for settings/ledger/grid. Flat hash router will strain if deep-linking into entities grows (bot/<id> exists; trade/<id>, decision/<id> don't). |

## 2. What was wrong (found in audit)

**Redundant / overlapping (fixed by regrouping, none deleted):**
- *Paper Trading* vs *Bot Terminal* — two "paper trading" pages. The terminal (live chart + decision engine + grid tester) is what the product is actually about; the old page is an account/blotter view. → Nav item **Paper Trading now opens the Bot Observation Terminal**; the classic view lives on as **Paper Account** (linked from the terminal header).
- *Strategies* vs *Strategy Studio* vs *Strategy Proof* — three strategy pages as siblings. → **Strategy Studio** is the nav entry; Catalog + Proof are one click away from its header.
- *Markets* vs *Symbols* — two market-browsing pages. → both linked from **Portfolio**.
- *Journal* vs *Decisions* vs *Memory* vs *Evolution* — four record-keeping pages. → **Records** group: Journal, **Decision Archive** (renamed from Decisions — it already stores taken/rejected/skipped/WAIT decisions, searchable), Memory; Evolution linked from Memory.
- *Safety Center* vs *Risk Manager* vs *Live Trading* — overlapping governance. → Live Trading + Risk Manager in nav; Safety Center linked from Live Trading.

**Missing (exists nowhere):**
- Optimization Lab (parameter sweeps / walk-forward optimizer as a first-class page — walk-forward folds exist inside Strategy Proof).
- Monte Carlo simulation on backtest results.
- Strategy version control / clone / side-by-side compare (Studio saves specs but has no history).
- Correlation matrix in Risk Manager (exposure/drawdown/limits exist; cross-asset correlation doesn't).
- Notifications center as a first-class surface (Alerts page exists but is hidden; no push/email prefs UI beyond Settings).
- Deep links for single trades/decisions (`#/bot/<id>` exists; `#/decision/<id>` doesn't).

**UX inconsistencies (fixed):**
- Default page was "Overview" while the top bar called it "Dashboard" → renamed everywhere to **Dashboard**.
- No visual grouping in a 20-item nav → 5 lifecycle groups with section labels.
- Old bookmarks (`#/overview`, `#/bot-terminal`, `#/decisions`) → legacy-slug aliases keep them working.

## 3. The new application flow

```
                       ┌──────────────┐
                       │  DASHBOARD   │  am I profitable? engine on? warnings?
                       └──────┬───────┘
          ┌────────────  TRADING  ─────────────┐
          │ Strategy Studio → Paper Trading    │  build → watch the bot trade it live
          │ → Replay → Backtesting → Grid&DCA  │  step through → prove on history
          │ → Live Trading (safety-gated)      │  → only then real money
          └──────────────────┬─────────────────┘
        ┌─────────────  PERFORMANCE  ───────────┐
        │ Portfolio → Analytics → AI Intelligence│  what happened → why → what to fix
        └──────────────────┬────────────────────┘
           ┌────────────  RECORDS  ─────────────┐
           │ Journal → Decision Archive → Memory │  every trade, every decision, every lesson
           └──────────────────┬──────────────────┘
             ┌────────────  SYSTEM  ────────────┐
             │ Risk Manager · Bot Health · Logs │  govern, monitor, debug
             │ · Settings                       │
             └──────────────────────────────────┘
```

## 4. New sidebar (implemented)

```
Dashboard
TRADING      Strategy Studio · Paper Trading · Replay · Backtesting · Grid & DCA · Live Trading
PERFORMANCE  Portfolio · Analytics · AI Intelligence
RECORDS      Journal · Decision Archive · Memory
SYSTEM       Risk Manager · Bot Health · Logs · Settings
```
17 visible items (was 20), 11 supporting pages one click from their parent:
Paper Account, Strategies, Strategy Proof, Markets, Symbols, Simulation, Evolution,
Safety Center, Alerts, AI Assistant, Bots. **Zero pages deleted; every old hash still resolves.**

## 5. Page-by-page audit (condensed)

| Page | Purpose | Verdict |
|---|---|---|
| Dashboard | Profitability, engine health, risk, activity at a glance | Answers all 9 dashboard questions (equity, strategy chip in header, warnings via WhyNoTrades + alerts, drawdown in Risk Center card, today's trades in activity). Keep. |
| Strategy Studio | No-code block builder → same engine as backtest/paper | Primary build surface. Missing: versioning/clone/compare (Phase 2). |
| Paper Trading (terminal) | THE observation lab: live chart, per-strategy viz, decision engine, entry checklist, confidence, grid tester, server grid, Developer mode | Heart of the app; answers "why entered / why skipped / why exited" via Decision Engine + checklist + Decision Reports. |
| Replay | Candle-by-candle step-through of decisions | Promoted to nav (was hidden). |
| Backtesting | Historical runs, equity curve, drawdown, trade list | Missing Monte Carlo + monthly-returns table (Phase 2/3). |
| Grid & DCA | Deterministic grid/DCA config + live preview + live testers | Keep. |
| Live Trading | Safety-gated live path, checklist, broker status | Correctly locked; Safety Center linked. |
| Portfolio | Allocation, exposure, long/short, risk level | Keep; now hosts Markets/Symbols links. |
| Analytics | Daily realized P&L, distributions | Missing per-condition/per-session breakdowns (partially in Strategy Proof) — Phase 3 consolidation. |
| AI Intelligence | Pattern/weakness/insight engine | Keep; add "apply suggestion" loop (Phase 2). |
| Journal | Searchable record of every journaled trade | Keep. |
| Decision Archive | One Decision Report per cycle incl. WAIT/rejections — searchable | Renamed from "Decisions"; this IS the requested archive. |
| Memory | Permanent per-trade memory, lessons, coaching | Keep; Evolution linked. |
| Risk Manager | Limits, drawdown, exposure, circuit breakers | Missing correlation matrix (Phase 3). |
| Bot Health | Watchdog, feed, skip log — operational truth | Keep (developer tool). |
| Logs | Live ledger log stream | Keep (developer tool). |
| Settings | Risk params (live-applied), env-set infra readouts | Keep. |

## 6. Priority roadmap

**Phase 1 — Critical (DONE in this change)**
- Lifecycle-grouped sidebar, dedupe, renames, legacy aliases, cross-links.
- (Previously shipped this session: shared polling cache, WS throttle+reconnect, grid warm-up fix — the perf part of "critical".)

**Phase 2 — Important**
- Strategy versioning: save history per spec, clone, diff two versions.
- "Apply suggestion" actions from AI Intelligence → Strategy Studio / Risk settings.
- Monthly-returns table + trade-distribution histogram in Backtesting.
- Notification center: promote Alerts with unread badge in the top bar.

**Phase 3 — Advanced**
- Optimization Lab page: parameter grid-search over the existing replay engine, walk-forward mode (reuse Strategy Proof folds), results matrix.
- Monte Carlo resampling of backtest trade lists (equity-path fan chart).
- Correlation matrix + per-symbol exposure caps in Risk Manager.
- Deep links: `#/decision/<id>`, `#/trade/<id>` for sharing/audit.

**Phase 4 — Institutional**
- Multi-account / multi-bot portfolios (the Bots page becomes a fleet manager).
- Strategy A/B allocation (capital split across strategies with per-sleeve risk).
- Exportable compliance pack: decision archive + config audit trail as signed PDF.
- Latency/slippage telemetry per venue once live trading unlocks.
