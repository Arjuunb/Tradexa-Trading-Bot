# Trading Operations System — spec coverage

A map from the 15-section Trading Operations spec to what actually ships. The
principle throughout: build the genuinely missing pieces properly and wire them
to real state; for everything already present, point at it honestly rather than
duplicate it.

## Newly built in this change

### §7 Trading Modes — `full` / `semi` / `signal`
`engine.trading_mode` (persisted via runtime settings, survives restart).
- **Full Auto** — qualifying setups execute automatically (unchanged behavior).
- **Semi-Auto** — each new ENTRY is queued for human approval instead of
  executing; approved ideas route through the SAME risk pipeline (nothing is
  bypassed). Exits/flips always execute automatically — a human must never have
  to approve getting *out* of a position.
- **Signal** — the engine records every setup as an alert and never places an
  order.
Endpoints: `GET/POST /engine/mode`. Switchable live on Paper Trading.

### §11 Trade Approval workflow — `services/approvals.py`
In-memory, TTL'd queue (a setup is only valid near the price/moment it fired;
approving a stale idea would place a trade at a price that no longer exists, so
ideas are deliberately not persisted across restarts). Each idea carries
symbol, direction, entry/stop/target, planned R:R, confidence, brain score and
the AI reason. Same-symbol/side dedup stops one ongoing setup from spamming the
queue. Expired and rejected ideas are graded by the counterfactual tracker like
any other missed entry. Endpoints: `GET /approvals`, `POST /approvals/{id}/approve`,
`POST /approvals/{id}/reject`. UI: the approval cards on Paper Trading.

### §9 Risk Profile presets — `RISK_PRESETS`
Conservative (0.5%/trade), Balanced (1%), Aggressive (2%) — each a coherent
bundle of risk-per-trade + max drawdown + daily-loss + exposure cap + max
positions. Custom points at Settings. Applies to the live engine and persists.
Endpoints: `GET /risk/presets`, `POST /risk/preset`. UI: the Risk Center presets.

## Already shipped (mapped, not rebuilt)

| Spec section | Where it lives today |
|---|---|
| §1 Bot Control Center / status / controls / live monitoring | **Bot Health** page + **Paper Trading** engine controls (Start/Pause/Stop/Resume/Emergency), `/system/status`, `/bot/health`, feed/latency/uptime |
| §1 Bot Health Score | **Bot Health** — API/feed/risk/watchdog status |
| §2 Strategy management / builder | **Strategies** page + `/strategy/list` + `/strategy/select`; entry/exit/filters are the engine's measured config (Settings) |
| §3 Backtesting Center | **Backtesting** + **Replay** + **Simulation** pages; equity/drawdown/monthly, walk-forward at `/strategy/walk-forward` |
| §4 AI Trading Memory | **Memory** page — 8-category permanent memory, insights, mistake library, **Growth Journey** |
| §5 AI Trade Explanation | **Decisions** page — per-cycle report: why entered / why skipped, checklist, 5-category score |
| §6 Market Intelligence | funding / econ-calendar / context gates (`services/context_brain.py`, `services/econ_guard.py`); Markets page |
| §7 Trading modes | **NEW** (above) |
| §8 Paper sandbox | the entire engine runs in paper by default; **Paper Trading** + **Strategy Proof** (paper vs backtest) |
| §9 Risk presets | **NEW** (above); full manual risk config already in Settings → Risk |
| §10 Multi-bot | shadow-run A/B (`services/shadow.py`) audition + per-symbol allocator; single live engine by design (honest: one capital pool) |
| §11 Trade approval | **NEW** (above) |
| §12 Notifications | Telegram/Discord/Email channels (`services/alerts.py`) + trade/risk alert toggles in Settings |
| §13 Mobile-ready | responsive dashboard; header quick-controls; approval cards work on mobile |
| §14 Security | trade-only keys / withdrawals impossible (**Safety Center**), session auth, audit ledger, per-user isolation |

## Honest notes

- **Multi-bot** (§10) is intentionally one live engine with a shadow auditor
  rather than N independent live bots sharing capital — running several live
  bots on one paper account would double-count capital and risk. The
  shadow/allocator machinery gives the "compare strategies" value without that
  hazard.
- **2FA** (§14) is not implemented; the Security page states this rather than
  faking a toggle.
- Approvals are session-lived by design (see above) — not a persistence gap.
