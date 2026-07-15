# Audit Phase 2 — correctness & performance

The audit's correctness/perf findings. Backend-only; each verified in-source and
covered by `tests/test_phase2_correctness.py` (6 tests).

## H-4 — position-cap check-then-open was not atomic
`SignalPipeline.process()` reads the open-position count, decides whether room
exists, then opens — a classic check-then-act. Under concurrent webhooks (the API
is threaded) two signals could both pass the cap check and both open, breaching
`max_open_positions`. **Fix:** `process()` now takes an `RLock` (`_proc_lock`) for
the whole check→size→open→ledger sequence; the body moved to `_process()`. The cap
now holds under a 12-thread burst (test).

## H-5 — paper_trades re-scanned ~10× per signal, unindexed
Every signal recomputes PnL / streak / Kelly / equity-curve, each scanning the full
`paper_trades` table, and the table had no index. **Fix:** (1) `PaperExecutionEngine.history()`
memoises the scan in `_hist_cache`, invalidated on every open/reduce/close, so one
signal does one scan instead of ~10; (2) added `idx_paper_status` and
`idx_paper_opened` so the status/time filters use an index instead of a table scan.

## M-9 — partial close recorded the original size, not the closed size
`reduce()` closed a fraction of a position but wrote the *original* full size on the
closed row, so per-trade R and size accounting were wrong for scale-outs. **Fix:**
`close_paper_trade` gained an optional `size=` param; `reduce()` passes the
actually-closed size. The closed row now shows the real closed size (e.g. 4 of 10),
the surviving row the remainder (6), and full closes are unchanged.

## M-8 — silent `except: pass` on bot lifecycle actions
`edit_bot` / bot start-stop / `go_live` swallowed every exception with `pass`, so a
failed action redirected to a fresh page with no trace and no user feedback. **Fix:**
each now logs the failure to the ledger (`stage="bots"`) and redirects with a
`?error=` message the UI can surface, instead of failing silently.

## Deferred — M-5 (webhook-secret scope)
The webhook secret is still accepted on all endpoints. Scoping it to `/webhook`
would break the cross-origin Vercel dashboard's control actions, which authenticate
with that header — an architecturally significant change flagged for a dedicated
pass. CR-1 (Phase 0) already removed the account-takeover vector by decoupling
session signing from the webhook secret, so this is lower urgency.
