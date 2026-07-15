"""Honest storage-durability assessment.

Answers one question truthfully: *will the bot's state survive a redeploy?*

The durability tiers, from best to worst:
  - "disk"     — HUB_DATA_DIR points at a mounted persistent disk. EVERY local
                 store (paper account, user accounts + settings, trade memory,
                 decisions, ledger) survives a redeploy.
  - "supabase" — no disk, but SUPABASE_URL/KEY are set and connected. Only the
                 LEDGER is Supabase-backed, so trade history survives — but the
                 paper account, users, saved settings and AI memory are still
                 local SQLite and are WIPED on redeploy.
  - "ephemeral"— no disk, no Supabase. Nothing survives a redeploy.

Used by GET /ops/storage (surfaced on Bot Health) and by a loud boot-time
warning, so an operator is never *silently* running on disposable storage.
"""
from __future__ import annotations

from typing import Optional

# Local-only stores — durable ONLY on a persistent disk (Supabase backs the
# ledger alone). Named in operator terms for the UI.
LOCAL_STORES = (
    "Paper account (capital / equity)",
    "User accounts + saved settings",
    "AI trade memory",
    "Decision & skip history",
)


def assess(*, data_dir: str, hub_data_dir_set: bool, on_cloud: bool,
           supabase_connected: bool) -> dict:
    """Pure durability assessment. ``on_cloud`` = running on Render/Heroku
    (where the app dir is ephemeral); off-cloud (local dev) is always durable."""
    disk = hub_data_dir_set
    # local stores survive a redeploy only on a mounted disk
    local_durable = disk or not on_cloud
    # the ledger additionally survives via Supabase
    ledger_durable = local_durable or supabase_connected

    if disk or not on_cloud:
        tier = "disk"
    elif supabase_connected:
        tier = "supabase"
    else:
        tier = "ephemeral"

    at_risk = [] if local_durable else list(LOCAL_STORES)

    warning: Optional[str] = None
    if tier == "ephemeral":
        warning = ("Storage is EPHEMERAL — every redeploy wipes ALL state "
                   "(paper account, user accounts, settings, AI memory, trade "
                   "history). Mount a persistent disk and set HUB_DATA_DIR, or "
                   "at minimum configure Supabase to preserve trade history.")
    elif tier == "supabase":
        warning = ("Trade history is preserved (Supabase), but the paper "
                   "account, user accounts, saved settings and AI memory are "
                   "still local and are WIPED on redeploy. Mount a persistent "
                   "disk and set HUB_DATA_DIR to make everything durable.")

    return {
        "tier": tier,
        "data_dir": str(data_dir),
        "hub_data_dir_set": hub_data_dir_set,
        "on_cloud": on_cloud,
        "supabase_connected": supabase_connected,
        "local_durable": local_durable,
        "ledger_durable": ledger_durable,
        # legacy field kept for the existing UI: overall "everything survives?"
        "persistent": local_durable,
        "at_risk": at_risk,
        "warning": warning,
    }


def boot_banner(assessment: dict) -> Optional[str]:
    """A multi-line stderr banner for boot when storage isn't fully durable, or
    None when everything survives a redeploy."""
    if assessment["local_durable"]:
        return None
    tier = assessment["tier"]
    lines = [
        "=" * 68,
        "  STORAGE DURABILITY WARNING",
        f"  Tier: {tier.upper()}  ·  data_dir: {assessment['data_dir']}",
        "  " + (assessment["warning"] or ""),
    ]
    if assessment["at_risk"]:
        lines.append("  At risk on next redeploy: " + ", ".join(assessment["at_risk"]))
    lines.append("=" * 68)
    return "\n".join(lines)
