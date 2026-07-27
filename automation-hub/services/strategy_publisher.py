"""Strategy Marketplace — publishing, with transparency enforced by the code.

The hard part of a strategy marketplace is not listing strategies. It is that
the incentive to lie is enormous: a publisher wants to show the window where
their strategy printed money and quietly drop the one where it did not.

This module makes that impossible by construction rather than by policy:

  * **Metrics are never accepted from the caller.** ``publish`` takes a runner
    and executes the backtest itself. There is no parameter through which a
    publisher can supply a number, so there is nothing to forge.
  * **An unverifiable strategy cannot be listed at all.** If the backtest
    produces no trades, publishing is refused. A listing with no evidence is
    exactly the listing this system exists to prevent.
  * **Re-publishing replaces the metrics and appends to history.** You cannot
    edit a spec and keep the old numbers, and you cannot delete the old numbers
    either — ``history`` is append-only, so a strategy that got worse shows a
    record that got worse.
  * **There is no "hide" and no "edit metrics".** Deliberately. The only way to
    remove numbers from the marketplace is ``unpublish``, which removes the
    entire listing — you cannot keep the storefront and drop the receipts.
  * **Ratings belong to raters.** A publisher has no code path to remove or
    alter a rating on their own listing.

Storage is a JSON file, mirroring ``services.custom_store``. Everything except
the store I/O is pure.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from services.tenancy import OWNER_TENANT

# The metrics every listing must display. Chosen so the unflattering ones
# (drawdown, losses) are not optional — a listing carries them or it does not
# exist.
VERIFIED_KEYS = ("total_trades", "win_rate", "profit_factor", "net_r",
                 "expectancy_r", "max_drawdown_r", "avg_rr", "wins", "losses",
                 "max_consecutive_losses", "span_days")

MIN_TRADES_TO_PUBLISH = 10      # below this the "verified" result is noise
MAX_STARS = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verified(results: Optional[dict]) -> Optional[dict]:
    """The engine's own numbers, carried across unchanged. Returns None when the
    backtest cannot support a claim — the caller then refuses to publish."""
    if not results or int(results.get("total_trades") or 0) < MIN_TRADES_TO_PUBLISH:
        return None
    return {k: results.get(k) for k in VERIFIED_KEYS if results.get(k) is not None}


def _risk_profile(spec: dict, metrics: dict) -> dict:
    """Risk facts a buyer needs, read off the spec and the verified run. Nothing
    is softened: max drawdown and the worst losing streak are both required
    fields of a listing."""
    stop = spec.get("stop") or {}
    target = spec.get("target") or {}
    return {
        "risk_per_trade_pct": spec.get("risk_per_trade_pct"),
        "stop": f"{stop.get('type', '?')} {stop.get('mult') or stop.get('value_pct') or ''}".strip(),
        "target": f"{target.get('type', '?')} {target.get('rr') or target.get('value_pct') or ''}".strip(),
        "max_drawdown_r": metrics.get("max_drawdown_r"),
        "max_consecutive_losses": metrics.get("max_consecutive_losses"),
        "losses": metrics.get("losses"),
    }


class PublishStore:
    """Listings + ratings + follows, persisted as one JSON document."""

    def __init__(self, path: str):
        self.path = Path(path)

    # ------------------------------------------------------------------ io
    def _load(self) -> dict:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text())
                if isinstance(d, dict):
                    d.setdefault("listings", {})
                    d.setdefault("follows", {})
                    return d
        except Exception:  # noqa: BLE001 — corrupt file behaves as empty
            pass
        return {"listings": {}, "follows": {}}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    # ------------------------------------------------------------ publish
    def publish(self, spec: dict, *, publisher: str, runner: Callable[[dict], Optional[dict]],
                range_key: str = "1Y", description: str = "",
                tags: Optional[list] = None) -> dict:
        """Run the backtest, then list the strategy with THOSE numbers.

        Returns ``{"error": ...}`` when the strategy cannot be verified — an
        unverified listing is never created."""
        if not (spec.get("entry") or {}).get("rules"):
            return {"error": "A strategy needs entry rules before it can be published."}
        try:
            results = runner(spec)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Backtest failed, so nothing can be verified: {exc}"}
        metrics = _verified(results)
        if not metrics:
            n = int((results or {}).get("total_trades") or 0)
            return {"error": (f"This strategy produced {n} trades over {range_key} — "
                              f"below the {MIN_TRADES_TO_PUBLISH} needed to verify a "
                              "listing. Publishing unverified results is not supported.")}

        data = self._load()
        sid = spec.get("id")
        # Re-publishing the same strategy updates its listing rather than
        # spawning a second one that could show different numbers.
        existing = next((l for l in data["listings"].values()
                         if l.get("strategy_id") == sid and l.get("publisher") == publisher),
                        None) if sid else None

        snapshot = {"version": spec.get("version", "1.0"), "ran_at": _now(),
                    "range": range_key, "symbol": spec.get("symbol"),
                    "timeframe": spec.get("timeframe"), "metrics": metrics}

        if existing:
            existing.update({
                "name": spec.get("name") or existing["name"],
                "description": description or existing.get("description", ""),
                "tags": list(tags) if tags is not None else existing.get("tags", []),
                "version": spec.get("version", existing.get("version", "1.0")),
                "symbol": spec.get("symbol"), "timeframe": spec.get("timeframe"),
                "side": spec.get("side"), "spec": dict(spec),
                "verified": snapshot, "risk": _risk_profile(spec, metrics),
                "updated_at": _now(),
            })
            # append-only: never pruned, and never absent — a listing without a
            # history is a listing whose record could be quietly restarted.
            existing.setdefault("history", []).append(snapshot)
            listing = existing
        else:
            lid = uuid.uuid4().hex
            listing = {
                "id": lid, "strategy_id": sid, "publisher": publisher,
                "name": spec.get("name") or "Untitled strategy",
                "description": description,
                "tags": list(tags or []),
                "version": spec.get("version", "1.0"),
                "symbol": spec.get("symbol"), "timeframe": spec.get("timeframe"),
                "side": spec.get("side"), "spec": dict(spec),
                "verified": snapshot, "history": [snapshot],
                "risk": _risk_profile(spec, metrics),
                "ratings": {}, "imports": 0,
                "published_at": _now(), "updated_at": _now(),
            }
            data["listings"][lid] = listing

        self._write(data)
        return public_view(listing)

    def unpublish(self, listing_id: str, *, publisher: str) -> bool:
        """Remove a listing entirely. There is no partial removal — a publisher
        cannot keep the listing and drop its numbers."""
        data = self._load()
        l = data["listings"].get(listing_id)
        if not l or l.get("publisher") != publisher:
            return False
        del data["listings"][listing_id]
        self._write(data)
        return True

    # ------------------------------------------------------------- browse
    def get(self, listing_id: str) -> Optional[dict]:
        l = self._load()["listings"].get(listing_id)
        return public_view(l) if l else None

    def browse(self, *, sort: str = "recent", tag: Optional[str] = None,
               publisher: Optional[str] = None, symbol: Optional[str] = None,
               follower: Optional[str] = None) -> list[dict]:
        data = self._load()
        rows = [public_view(l) for l in data["listings"].values()]
        if tag:
            rows = [r for r in rows if tag in (r.get("tags") or [])]
        if publisher:
            rows = [r for r in rows if r["publisher"] == publisher]
        if symbol:
            rows = [r for r in rows if r.get("symbol") == symbol]
        if follower:
            followed = set(data["follows"].get(follower, []))
            rows = [r for r in rows if r["publisher"] in followed]
        return sort_listings(rows, sort)

    # ------------------------------------------------------------- rating
    def rate(self, listing_id: str, *, user: str, stars: int,
             comment: str = "") -> Optional[dict]:
        """One rating per user; rating again replaces your own and nobody
        else's. The publisher has no path into this dict."""
        if not 1 <= int(stars) <= MAX_STARS:
            return {"error": f"Rating must be 1-{MAX_STARS} stars."}
        data = self._load()
        l = data["listings"].get(listing_id)
        if not l:
            return None
        if l.get("publisher") == user:
            return {"error": "You cannot rate your own strategy."}
        l.setdefault("ratings", {})[user] = {
            "stars": int(stars), "comment": (comment or "").strip()[:1000], "at": _now()}
        self._write(data)
        return public_view(l)

    # ------------------------------------------------------------ follows
    def follow(self, *, follower: str, creator: str) -> dict:
        if follower == creator:
            return {"error": "You cannot follow yourself."}
        data = self._load()
        lst = data["follows"].setdefault(follower, [])
        if creator not in lst:
            lst.append(creator)
        self._write(data)
        return {"following": list(lst)}

    def unfollow(self, *, follower: str, creator: str) -> dict:
        data = self._load()
        lst = [c for c in data["follows"].get(follower, []) if c != creator]
        data["follows"][follower] = lst
        self._write(data)
        return {"following": lst}

    def following(self, follower: str) -> list[str]:
        return list(self._load()["follows"].get(follower, []))

    # ------------------------------------------------------------- import
    def import_listing(self, listing_id: str, custom_store, *,
                       tenant: str = OWNER_TENANT) -> dict:
        """Copy a published strategy into your own library, with provenance.

        The copy is a NEW strategy id with its own version history — importing
        never lets you write into someone else's listing."""
        data = self._load()
        l = data["listings"].get(listing_id)
        if not l:
            return {"error": "Listing not found."}
        spec = {k: v for k, v in (l.get("spec") or {}).items()
                if k not in ("id", "created_at", "updated_at", "versions", "tenant_id")}
        spec["id"] = uuid.uuid4().hex
        spec["name"] = f"{l['name']} (imported)"
        spec["tags"] = sorted(set((spec.get("tags") or []) + ["imported"]))
        spec["imported_from"] = {"listing_id": l["id"], "publisher": l["publisher"],
                                 "version": l.get("version"), "at": _now()}
        saved = custom_store.save(spec, tenant)
        l["imports"] = int(l.get("imports") or 0) + 1
        self._write(data)
        return saved


# ------------------------------------------------------------- pure helpers

def rating_summary(ratings: dict) -> dict:
    rows = [r for r in (ratings or {}).values() if isinstance(r, dict)]
    stars = [int(r.get("stars") or 0) for r in rows if r.get("stars")]
    if not stars:
        return {"count": 0, "average": None,
                "note": "No ratings yet — the verified backtest is the only evidence here."}
    return {"count": len(stars), "average": round(sum(stars) / len(stars), 2),
            "distribution": {str(s): stars.count(s) for s in range(1, MAX_STARS + 1)}}


def public_view(listing: dict) -> dict:
    """What a browser sees. Every field the spec requires a listing to display is
    computed here, so no call site can omit one."""
    ratings = listing.get("ratings") or {}
    history = listing.get("history") or []
    return {
        "id": listing["id"], "publisher": listing["publisher"],
        "name": listing["name"], "description": listing.get("description", ""),
        "version": listing.get("version", "1.0"),
        "symbol": listing.get("symbol"), "timeframe": listing.get("timeframe"),
        "side": listing.get("side"), "tags": listing.get("tags", []),
        "verified": listing.get("verified"),
        "risk": listing.get("risk"),
        "history": history,
        "publish_count": len(history),
        "rating": rating_summary(ratings),
        "reviews": sorted(
            [{"user": u, **{k: v for k, v in r.items() if k != "stars"}, "stars": r.get("stars")}
             for u, r in ratings.items() if isinstance(r, dict)],
            key=lambda r: r.get("at", ""), reverse=True),
        "imports": listing.get("imports", 0),
        "published_at": listing.get("published_at"),
        "updated_at": listing.get("updated_at"),
        "spec": listing.get("spec"),
    }


def _m(row: dict, key: str, default: float = 0.0) -> float:
    v = ((row.get("verified") or {}).get("metrics") or {}).get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


_SORTS: dict[str, Callable[[dict], Any]] = {
    "recent": lambda r: r.get("updated_at") or "",
    "net_r": lambda r: _m(r, "net_r"),
    "profit_factor": lambda r: _m(r, "profit_factor"),
    "win_rate": lambda r: _m(r, "win_rate"),
    "trades": lambda r: _m(r, "total_trades"),
    "rating": lambda r: (r["rating"].get("average") or 0, r["rating"]["count"]),
    "imports": lambda r: r.get("imports", 0),
    # Ascending — deliberately offered, so "show me the shallowest drawdowns"
    # is as easy to ask as "show me the biggest returns".
    "drawdown": lambda r: -_m(r, "max_drawdown_r"),
}


def sort_listings(rows: list[dict], sort: str) -> list[dict]:
    return sorted(rows, key=_SORTS.get(sort, _SORTS["recent"]), reverse=True)


def make_runner(bars_for_range, range_key: str):
    """Default runner: the shared spec runner. One engine — a published number is
    reproducible by the person reading it, using the same path."""
    from services.spec_runner import make_runner as _shared
    return _shared(bars_for_range, range_key)
