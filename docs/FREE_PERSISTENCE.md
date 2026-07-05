# Free persistence — keep capital/trades across redeploy without paying

Render's free tier has an **ephemeral disk**: when the service spins down (after
~15 min idle) or you redeploy, local SQLite files are wiped, so paper capital
reverts to the default. You do **not** need a paid disk to fix this. Two free
options, best first.

---

## Option A — Free Supabase Postgres (recommended: true persistence)

The app already supports Supabase as the source of truth (`supabase>=2.0` is
installed; `get_ledger()` auto-uses it when the env vars are set). Free tier:
500 MB Postgres, no time limit.

**Setup (~5 min):**

1. Create a free project at <https://supabase.com> (no card required).
2. In the Supabase dashboard → **SQL Editor**, paste and run
   [`automation-hub/data/ledger_schema.sql`](../automation-hub/data/ledger_schema.sql)
   (it creates `webhook_events`, `positions`, `paper_trades`, `bot_logs`,
   `alerts`).
3. In **Project Settings → API**, copy the **Project URL** and a key
   (the **service_role** key for full read/write from the backend).
4. On Render → your service → **Environment**, set:
   - `SUPABASE_URL` = the project URL
   - `SUPABASE_KEY` = the key
   - (optional) `HUB_STARTING_CASH` = your starting capital (e.g. `10000`)
5. **Redeploy.**

**Result:** trades, positions and logs live in Postgres, so
`current_equity = HUB_STARTING_CASH + realized P&L` **survives redeploys and
spin-downs — for free.** The Paper Trading page will show the persistence
warning gone and `storage: "supabase"`.

**Honest limits:** the ledger (capital + trade history) persists. The newer
decision-journal, skipped-trade log, validation snapshots and *custom*
initial-capital edits are still SQLite-only, so those specific logs reset on
redeploy unless you also set `HUB_DATA_DIR` (paid disk) or we extend them to
Supabase later. Your **capital does not reset** — that is what Option A fixes.

Set a custom starting capital for free with `HUB_STARTING_CASH` (env config
survives redeploys); the in-app "Set initial capital" editor writes to the local
store, which is not persistent on free tier.

---

## Option B — Free keep-alive ping (zero setup, prevents spin-down)

If you just want "logout → login later doesn't reset," and you rarely redeploy,
stop the free tier from spinning down. While the instance stays up, its SQLite
file persists between sessions.

1. Sign up for a free uptime monitor — e.g. **UptimeRobot** or **cron-job.org**
   (both free).
2. Add an HTTP(s) monitor hitting `https://<your-app>.onrender.com/health`
   every **10 minutes**.

**Result:** the service never idles out, so capital/trades survive across
logout/login the same day — free, no code.

**Honest limit:** a **redeploy** (new code push) or a platform restart still
wipes the local disk. Option B avoids spin-down loss, not redeploy loss. For
redeploy-proof persistence use Option A.

---

## Which should I use?

| Need | Use |
|---|---|
| Capital + trades survive **redeploys**, free | **A (Supabase)** |
| Just avoid spin-down resets, zero setup | **B (keep-alive)** |
| Best of both | A **and** B |
| Everything (journal, skip logs, snapshots) survives | A + `HUB_DATA_DIR` on a paid disk, or a future Supabase extension |

Live trading stays locked in every option — this is about persisting **paper**
capital and history only.
