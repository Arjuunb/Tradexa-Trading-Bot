# TradeLogX Nexus — Testing & Quality Assurance Report

*Pre-production QA audit. Report-only — no product code was modified during testing. Companion to the blueprint set + `MVP_COMPLETION.md`.*

> **Version 1.0 · 2026-07-22 · Evidence-based: every green/red below is a real command run against this repo.**

---

## 0. Method & honesty note (read first)

This is a **verification report, not a claim.** Where a result is stated, it comes from an actual run:

| Suite | Command | Result (measured) |
|---|---|---|
| Backend | `automation-hub $ python -m pytest -q` | **870 passed, 3 warnings — 170.25 s** |
| Root / Vercel | `$ python -m pytest tests -q` | **96 passed — 3.27 s** |
| Dashboard build | `automation-hub-dashboard $ npm run build` | **✓ built in 10.46 s** (1 bundle-size warning) |
| Landing build | `tradexa-landing $ npm run build` | **✓ built in 5.02 s** (code-split) |
| Test inventory | `ls tests` | **129 test files** (107 backend + 22 root) |

**Two things this report will NOT do**, because doing so would violate the honesty standard the product itself enforces:
1. **It will not fabricate stress-test numbers.** Load tests at 100 / 1 000 / 10 000 users were **not executed** in this environment (no load harness, no multi-instance deploy). Reporting invented p95/CPU figures would be exactly the fake data this platform refuses. §6 states what *was* measured, what the architecture *implies*, and what the load tests must measure — with no invented values.
2. **It will not claim a pen-test that wasn't run.** §5 is a **code-inspection security audit** (real, grounded in the source), explicitly labeled as such — not a dynamic penetration test.

---

## 1. Functional Test Report

**Automated coverage:** 966 tests green (870 backend + 96 root), 129 test files. Per-module functional status (wiring verified in the MVP audit; behaviour covered by the suites):

| Module | Automated coverage | Wiring | Status |
|---|---|---|---|
| **Authentication** | `test_auth*`, session/HMAC, signup email-as-username | real (Supabase landing + HMAC cookie) | ✅ PASS |
| **Dashboard** | card data-source tests via API | live endpoints | ✅ PASS |
| **Strategy Studio** | `test_strategy*`, builder, custom store (+tenancy) | 13 live endpoints | ✅ PASS |
| **Paper Trading** | `test_paper*`, cash accounting, close/partial | `/paper/*` | ✅ PASS |
| **Replay Mode** | replay build + stats | `/replay` + honest data-real meta | ✅ PASS |
| **Backtesting** | `test_backtester`, `test_multi_backtester`, `test_walkforward` | real; `available:false` when thin | ✅ PASS |
| **Portfolio** | portfolio-risk, correlation | `/portfolio/*` | ✅ PASS |
| **Analytics** | metrics, distribution, equity | derived from real trades + offline state | ✅ PASS |
| **AI Intelligence** | `test_ai*`, coach, confidence, calibration | `/ai/*` with honest gating | ✅ PASS |
| **Journal** | journal store + events + tenancy | `/journal` | ✅ PASS |
| **Decision Archive** | decision store, cycle store | `/decision*` | ✅ PASS |
| **Risk Manager** | `test_risk_limits`, drawdown, correlation, sizing | 11 `/risk/*` | ✅ PASS |
| **Settings** | settings persistence + mirror + tenancy | 12 endpoints, honest LOCKED rows | ✅ PASS |

**Verdict:** All 13 functional modules pass automated coverage and are wired to real data. No functional regressions.

---

## 2. API Test Report

- **REST endpoints (~253):** exercised through the backend suite (router tests hit auth tiers, validation, and handlers). FastAPI auto-validates request models (Pydantic) and emits `/openapi.json`.
- **Authentication/Authorization:** verified — global auth wall (`_require_auth`), session cookie + `X-Webhook-Secret` tiers, `_check_secret` on writes; unauth → `401`. Tests confirm 401 on protected routes, 200 with credential.
- **Validation:** Pydantic on typed handlers (✅); **gap:** several write handlers take untyped `dict = Body(...)` → loose schema (documented, API §8).
- **Rate limiting:** verified on `/login`, `/signup` (12/5 min) and `/webhook` (120/min); **gap:** not applied to the other ~250 routes (API §9).
- **Error handling:** two shapes today (`{"error":…}` hand-written vs `{"detail":…}` framework) — **inconsistent**, normalization is the `/api/v1` envelope target (API §6/§7).
- **WebSocket events:** **N/A today** — there are no WS endpoints; realtime is SSE (`/events/stream`) + a 2.5 s `useLive` poller. The WS gateway is a target (API §5). *Cannot be "verified" because it does not yet exist — reported as MISSING, not FAIL.*

**Verdict:** REST layer PASS (functional); envelope/validation/rate-limit normalization + WS gateway are known gaps, not defects.

---

## 3. Database Test Report

- **CRUD:** verified across all stores (paper trades, positions, journal, decisions, cycles, skipped, trade memory, settings, custom strategies) — the suites create/read/update/delete against real SQLite.
- **Migrations:** forward-only runner (`database/migrations/000{1,2,3}`) with a `_migrations` tracking table — applied on boot, tested.
- **Transactions:** SQLite with `busy_timeout` + per-store locks (`RLock`) serializing request + engine threads; the pipeline is lock-serialized.
- **Relationships/Indexes:** indexes exist on hot columns (`status`, `ts`, `symbol`, `opened_at`); **gap:** **no foreign keys** (SQLite FKs off) and non-UUID keys — the Postgres/RLS/FK target (DDS).
- **Backups:** Supabase mirror (`SupabaseLedger`/settings) provides durability when configured; **gap:** **no PITR / restore-drill** documented (DDS §9).
- **Tenancy:** `tenant_id` + `ensure_tenant_column` on the pilot + flat stores (Phase C ✅), inert until `HUB_MULTI_USER`; **RLS not yet enforced** (design only).

**Verdict:** CRUD/migrations/transactions PASS on SQLite. FKs, RLS, UUIDs, and PITR are the Postgres-migration gaps (not bugs at current scope).

---

## 4. Trading Engine Validation

This is the brief's central QA question: *do Paper, Replay, Backtesting, and Live produce consistent results on identical data + settings?*

**Evidenced answer: PARTIALLY VERIFIED — and this is the report's most important finding.**

- ✅ **Proven:** `tests/test_live_step.py` asserts the **root backtester's** incremental `step()+finalize()` equals its batch `run()` bit-for-bit (`ending_equity` + trade count) on seeded data — the guarantee that **backtest ≡ the live-runner** (which reuses `Backtester.step`). Determinism confirmed (`generate_bars(seed=…)` is reproducible).
- ✅ **Verified components:** signal generation, risk management (~18 gates), position sizing (risk%/ATR), trade management (BE/scale/trail/time — off by default, measured), trade closing, partial close, logging — all covered by the suites (`test_atr_sizing`, `test_risk_limits`, `test_trade_mgmt`, `test_trailing_stop`, `test_cash_accounting`, …).
- ❌ **NOT proven — the gap:** there is **no cross-mode equivalence test** covering the **flagship paper engine** (`AutoStrategyEngine`) against the **replay engine** (`services/replay.py`) against the **hub backtest-lab** (`automation-hub/backtest.py`). Per TES §9 these are **separate loops** that share the brain but duplicate fill/exit logic. So "identical results across paper/replay/backtest" is **asserted by design intent, not verified by a test**.
- ⚠️ **Live trading:** unverifiable — `LiveExecutionEngine` is an intentional stub (`NotImplementedError`); leverage is analytical only. Live consistency **cannot** be validated until the `BrokerFill` adapter exists.

**Verdict:** Individual engine behaviours PASS; the cross-mode consistency the brief requires is **HIGH-priority unverified** (Bug QA-1). The fix is the `TradeCore` unification + the equivalence suite (TES §19/§20, Sprint 3).

---

## 5. Security Audit (code inspection — not a dynamic pen-test)

| Vector | Finding | Rating |
|---|---|---|
| **Authentication** | HMAC-signed cookie (`HUB_SECRET`, 7-day), PBKDF2-HMAC-SHA256 200k iters, constant-time verify, fail-closed boot on default secret. **Solid.** | ✅ PASS |
| **Authorization** | session/secret tiers enforced; **gap:** only `is_admin` (no RBAC). | 🟡 |
| **SQL injection** | All queries use **parameterized** `?` placeholders (verified across stores); table names in `ensure_tenant_column` are internal literals, not user input. | ✅ PASS |
| **XSS** | App is a **JSON API + React** (auto-escapes); no `dangerouslySetInnerHTML` on user data on the core paths; legacy server-rendered pages use an escaper. | ✅ PASS (spot-checked) |
| **CSRF** | **gap:** cookie path is `SameSite=Lax` with **no CSRF token**; writes also require the `X-Webhook-Secret` header, which mitigates but isn't a token. Bearer/JWT path (target) is CSRF-immune. | 🟡 |
| **JWT** | not implemented (HMAC cookie today) — target. | 🔴 (scope) |
| **API keys / secrets** | exchange/provider keys never returned by the API; fail-closed boot guard; **gap:** exchange keys not yet encrypted-at-rest (paper-only today, no live keys stored). | 🟡 |
| **Sensitive data** | passwords hashed (never stored/returned plain); honest markers instead of leaking config. | ✅ PASS |
| **Rate limiting** | auth + webhook only, in-process; **gap:** per-module + distributed (Redis) is target. | 🟡 |
| **CORS** | env allow-list (`HUB_CORS_ORIGINS`), credentials off; warns loudly on `*` in cloud. | ✅ PASS |

**Verdict:** No injection/XSS/secret-leak vulnerabilities found by inspection. The gaps (RBAC, CSRF token, JWT, encrypted exchange keys, per-module limits) are the multi-tenant/live hardening set (API §8, DDS §8) — appropriate to defer for a single-owner paper MVP, **required** before multi-user/live. *A dynamic pen-test + dependency/secret scan should run in CI before a live release.*

---

## 6. Performance Test Report

**Measured (real):**
- Backend suite (966 tests incl. engine, backtests, Monte-Carlo): **170 s** — healthy.
- Dashboard build **10.46 s**; **⚠ one chunk > 500 KB** (Rollup warns; no `manualChunks` splitting) — a real front-end perf finding (Bug QA-4).
- Landing build **5.02 s**, already code-split (largest chunk 457 KB / 138 KB gz).
- Candle chart sets `animation:false` (✅ perf-correct on the hot path); `useLive` poller dedupes/backs-off/pauses on hidden tabs (✅).

**NOT executed (stated honestly, no invented numbers):**
- **Load/stress at 100 / 1 000 / 10 000 concurrent users** — **not run** (no load harness or multi-instance deploy in this environment). Therefore latency/CPU/memory/DB-load figures under load are **UNKNOWN and not estimated here.**
- **Architectural implication (not a measurement):** the system is a **single-process FastAPI app with one in-process engine loop and SQLite** (SAD §11). This means: SQLite serializes writes; one engine loop can't scale horizontally; there is no Redis/pool. **These are known ceilings** — 10 000 concurrent users is *architecturally* out of reach today without the Postgres + per-tenant-worker + PgBouncer/Redis work (Sprint 10). The honest statement is: **the current target is a single-owner deployment, for which measured build/test performance is healthy; multi-thousand-user load is untested and architecturally unsupported until the scale work lands.**
- **What the load tests must measure (Sprint 11, k6):** p50/p95/p99 latency per endpoint class (read < 150 ms, list < 300 ms, analytics < 800 ms targets), WS fan-out < 250 ms, DB connections under PgBouncer, engine cycle time under N tenants, memory/CPU ceilings.

**Verdict:** Single-owner performance PASS (measured); scale performance UNTESTED + architecturally gated (not a regression — a scope boundary).

---

## 7. UI/UX Audit

- **Responsive:** mobile drawer + scrim verified (720 px breakpoint); **gap:** intermediate tiers (1024/1280/1440/1600) not first-class (UDS §6).
- **Dark mode:** dark-first, consistent; **no light theme** (by design today).
- **Loading/empty/error states:** shared `useLive` exposes `loading`/`error`; data pages surface an offline card; honest empty states (`WhyNoTrades`, `OfflineBanner`). **Good; not every page has a distinct skeleton.**
- **Animations:** landing uses framer-motion + reduced-motion global block; **gap:** dashboard uses CSS transitions with only one reduced-motion rule (UDS §10).
- **Consistency:** two styling engines (dashboard CSS-vars + ECharts; landing Tailwind), two golds, dashboard doesn't load its declared fonts — **cross-app inconsistency** (UDS §20). Real, cosmetic, non-blocking.
- **Builds:** both apps compile clean (evidence above).

**Verdict:** PASS for a premium single-app experience; the cross-app design-system convergence (UDS §20) is polish, not a blocker.

---

## 8. Accessibility Audit (WCAG 2.2 AA)

**Real wins (verified in code):**
- ✅ **Never color-only:** numbers sign-prefixed `+`/`−` (U+2212) via `lib/format.ts`.
- ✅ **Focus visible:** 2 px gold `:focus-visible` outline + ring, both apps.
- ✅ **Landmarks/ARIA:** `<nav>/<aside>/<main>`, `aria-label` on logo, `aria-hidden` on decorative icons; Escape-closes-drawer.
- ✅ **Reduced motion:** global block on the landing.
- ✅ **Error resilience:** route-level `ErrorBoundary`.

**Gaps (findings, not blockers for a paper MVP):**
- 🟡 Modal **focus-trap** not universal; keyboard operation of all overlays unverified by automated axe.
- 🟡 Dashboard **reduced-motion** covers one rule only.
- 🟡 Screen-reader **live regions** for streaming price/toasts not declared.
- 🟡 Contrast: `--muted #7C8798` must be confined to ≥14 px non-essential text (verify all pairs).

**Verdict:** Above baseline; **no automated axe run in CI yet** (recommended, UDS §18). Manual keyboard + SR pass advised before a public launch.

---

## 9. Bug List (prioritized)

No **Critical** bugs found. Findings with evidence, repro, and fix:

### 🔴 Critical — none.

### 🟠 High
**QA-1 — No cross-mode equivalence test for the flagship paper engine.**
- *Evidence:* `test_live_step.py` covers only the root backtester's `step()==run()`; `AutoStrategyEngine`, `services/replay.py`, and `automation-hub/backtest.py` are separate loops (TES §9).
- *Steps to reproduce:* grep the test suite for a test feeding identical bars+seed+config through paper vs replay vs backtest and asserting equal trades/P&L → none exists.
- *Expected:* identical results across sim modes (brief requirement).
- *Actual:* consistency is asserted by design, not verified; divergence could go undetected.
- *Suggested fix:* build `TradeCore` + the equivalence suite (TES §19/§20, Sprint 3). **Until then, "consistent across modes" is unproven — do not advertise it as guaranteed.**

**QA-2 — Float money on paper P&L.**
- *Evidence:* ledger P&L columns are `REAL` (SQLite float); DDS mandates `NUMERIC(20,8)`.
- *Expected:* exact decimal money.
- *Actual:* float rounding acceptable for simulation, **unacceptable for live capital**.
- *Fix:* migrate money columns to `NUMERIC` during the Postgres move (DDS §2.2, Sprint 4). **Blocker for live, not for paper.**

### 🟡 Medium
**QA-3 — FastAPI `on_event` deprecation (3 warnings).**
- *Evidence:* backend run emits `on_event(event_type) # ty: ignore[deprecated]` ×3.
- *Actual:* works now; will break on a future FastAPI major.
- *Fix:* migrate startup/shutdown to the `lifespan` context manager.

**QA-4 — Dashboard bundle > 500 KB (no code-splitting).**
- *Evidence:* Rollup warns "some chunks are larger than 500 kB"; no `manualChunks`.
- *Actual:* slower first paint on cold loads.
- *Fix:* route-based lazy chunks + `manualChunks` for ECharts/reactflow (UDS §14 perf).

**QA-5 — Rate limiting only on auth + webhook.**
- *Evidence:* limiter applied to `/login|/signup|/webhook` only.
- *Actual:* the other ~250 routes are unthrottled → abuse/DoS surface.
- *Fix:* per-module Redis-backed buckets (API §9, Sprint 10). *(Deferred acceptable for single-owner.)*

**QA-6 — Inconsistent error envelope.**
- *Evidence:* `{"error":…}` vs `{"detail":…}`.
- *Fix:* one exception handler → the standard error envelope (API §7).

**QA-7 — Stress/load behavior unknown.**
- *Evidence:* no load tests executed; single-process + SQLite ceilings (SAD §11).
- *Fix:* k6 load suite + the scale work (Sprint 10/11). *(Scope boundary for single-owner.)*

### 🟢 Low
- **QA-8** — Cross-app design drift (two golds, dashboard fonts not loaded, `--purple`=gold) — UDS §20.
- **QA-9** — A11y polish: modal focus-trap, dashboard reduced-motion, SR live regions.
- **QA-10** — No automated axe/visual-regression/contract gates in CI yet.
- **QA-11** — `landing/settings/Advanced.tsx` inert `disabled` switches with no-op `onChange` — **confirm intentional** (read-only status), else wire or remove.
- **QA-12** — Untyped `dict = Body(...)` handlers weaken OpenAPI/validation (API §8).

---

## 10. Production Readiness Score

Scored against **two** deployment targets (the honest framing from `MVP_COMPLETION.md`).

### As a single-owner paper-trading platform
| Area | Score | Evidence |
|---|---:|---|
| Functional correctness | 9/10 | 966 tests green; all modules wired. |
| Data integrity (no fake data) | 10/10 | MVP audit Bucket A empty. |
| Test coverage | 8/10 | 129 files; cross-mode gap. |
| Security (single-owner) | 7/10 | Parameterized SQL, hashed pw, fail-closed boot. |
| Performance (single-owner) | 8/10 | Healthy build/test; chart perf good. |
| Stability | 8/10 | Exception-isolated engine, error boundary. |
| Accessibility | 6/10 | Real wins; polish + axe gate pending. |
| **Overall (paper MVP)** | **8.0 / 10** | **Production-ready for its scope.** |

### As a multi-tenant, live-money SaaS
| Area | Score | Blocker |
|---|---:|---|
| Cross-mode validation | 3/10 | QA-1 (no equivalence test) |
| Money precision | 2/10 | QA-2 (float) |
| Scale/load | 3/10 | QA-7 (untested + gated) |
| Security hardening | 4/10 | RBAC/JWT/CSRF/encrypted keys |
| Live trading | 2/10 | stub |
| **Overall (live SaaS)** | **≈ 4 / 10** | **Sprint 3–12.** |

---

## 11. Go / No-Go Release Recommendation

### ✅ GO — for a **single-owner, paper-trading** production release
**Conditions (all currently satisfiable):**
- `HUB_MULTI_USER=0` (single-owner) · `HUB_SECRET` set (fail-closed verified) · `HUB_CORS_ORIGINS` locked to real origins.
- Supabase mirror connected for durability; persistent disk on Render.
- Ship the release checklist (`MVP_COMPLETION.md` §8): smoke run login → start paper bot → real decision appears.
- **Marketing/UX must not claim** "identical results across paper/replay/backtest/live" as *guaranteed* until QA-1 is closed — state it as *designed-for*, not *verified*.
- Recommended-before-GA (not blockers): fix QA-3 (lifespan), QA-4 (bundle split), add an axe check.

### ⛔ NO-GO — for a **multi-tenant or live-money** release
Blocked until: QA-1 (`TradeCore` + equivalence suite), QA-2 (`NUMERIC` money), the live `BrokerFill` adapter, Postgres + RLS + isolation tests, JWT/RBAC + per-module rate limits + encrypted exchange keys, observability + PITR, and an executed load test. This is precisely the Sprint 3–12 scope; do not enable `HUB_MULTI_USER=1` or real capital before the DDS/SAD flip-criteria are all green.

### One-line verdict
> **GO to ship the paper-trading MVP now (8.0/10, zero fake data, 966 tests green). NO-GO on live money / multi-tenant until the roadmap's convergence + hardening lands. No Critical bugs; the one High finding (cross-mode equivalence unproven) is a truth-in-advertising constraint, not a crash.**

---

*End of Testing & QA Report v1.0. No product code was modified. Every result is reproducible with the commands in §0.*
