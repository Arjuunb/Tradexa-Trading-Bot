"""Strategy collaboration — diff, change log, comments, permissions.

Versioning already existed: every save that changes a strategy's definition
snapshots the previous state (``services.custom_store``). What was missing is
everything a *team* needs on top of that history.

Two halves, and the split matters:

  **Derived (cannot lie).** ``diff_specs`` and ``changelog`` are pure functions
  over the stored snapshots. Nobody writes a change note; the note IS the
  difference between two saved specs. A team member reading "RSI threshold
  55 -> 60" is reading the spec, not somebody's summary of it. This is what
  keeps "every version must remain reproducible" true — the log cannot drift
  from the artefact because it is computed from the artefact.

  **Authored (people's words).** Comments are opinions and belong to their
  authors: only an author edits or deletes their own comment, and a comment
  anchored to a version stays anchored even after the strategy moves on, so the
  discussion history stays legible.

Permissions are per-strategy grants layered on the account role from
``services.rbac``. They can only ever REDUCE what a grant gives you relative to
the owner: sharing hands out ``viewer``/``commenter``/``editor``, never
ownership, and the owner cannot be demoted out of their own strategy.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ascending: what a collaborator may do with someone else's strategy.
SHARE_ROLES: tuple[str, ...] = ("viewer", "commenter", "editor")
_SHARE_RANK = {r: i for i, r in enumerate(SHARE_ROLES)}

# Capability -> minimum share role.
SHARE_CAPABILITIES: dict[str, str] = {
    "view": "viewer",
    "comment": "commenter",
    "edit": "editor",
    "restore": "editor",
}

# Spec keys that are library bookkeeping, not the strategy definition. Excluded
# from diffs so "you favourited it" never appears as a strategy change.
_META_KEYS = {"id", "created_at", "updated_at", "versions", "favorite", "tags",
              "folder", "tenant_id", "imported_from"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _definition(spec: Optional[dict]) -> dict:
    return {k: v for k, v in (spec or {}).items() if k not in _META_KEYS}


# ------------------------------------------------------------------- diffing

def _rule_key(rule: dict) -> str:
    """Identity of a rule for diff purposes: its type plus its direction. Two
    RSI rules with different thresholds are the SAME rule changed, not one added
    and one removed — which is the difference between a readable log and noise."""
    return f"{rule.get('type', '?')}::{rule.get('dir', '')}{rule.get('op', '')}"


def _rules(spec: dict) -> list[dict]:
    return [r for r in ((spec.get("entry") or {}).get("rules") or [])
            if isinstance(r, dict)]


def _describe_rule(rule: dict) -> str:
    parts = [str(rule.get("type", "rule"))]
    for k, v in rule.items():
        if k != "type":
            parts.append(f"{k}={v}")
    return " ".join(parts)


def _scalar_changes(before: dict, after: dict, path: str = "") -> list[dict]:
    """Recursive value-level diff over the non-rule parts of a spec."""
    out: list[dict] = []
    for key in sorted(set(before) | set(after)):
        if key in ("entry",):                    # rules are diffed separately
            continue
        p = f"{path}.{key}" if path else key
        b, a = before.get(key), after.get(key)
        if isinstance(b, dict) and isinstance(a, dict):
            out.extend(_scalar_changes(b, a, p))
        elif b != a:
            kind = "added" if key not in before else "removed" if key not in after else "changed"
            out.append({"kind": kind, "field": p, "before": b, "after": a})
    return out


def diff_specs(before: Optional[dict], after: Optional[dict]) -> dict:
    """Structured difference between two strategy definitions.

    Returns ``{changed, rules: [...], fields: [...], summary: [...]}``. Nothing
    here is authored — every line is derived from the two specs, so a change log
    built on it cannot claim a change that did not happen."""
    b, a = _definition(before), _definition(after)
    fields = _scalar_changes(b, a)

    br, ar = _rules(b), _rules(a)
    b_by, a_by = {}, {}
    for r in br:
        b_by.setdefault(_rule_key(r), []).append(r)
    for r in ar:
        a_by.setdefault(_rule_key(r), []).append(r)

    rules: list[dict] = []
    for key in sorted(set(b_by) | set(a_by)):
        bl, al = b_by.get(key, []), a_by.get(key, [])
        for i in range(max(len(bl), len(al))):
            rb = bl[i] if i < len(bl) else None
            ra = al[i] if i < len(al) else None
            if rb is None:
                rules.append({"kind": "added", "rule_type": (ra or {}).get("type"),
                              "after": ra, "before": None,
                              "text": f"added {_describe_rule(ra or {})}"})
            elif ra is None:
                rules.append({"kind": "removed", "rule_type": rb.get("type"),
                              "before": rb, "after": None,
                              "text": f"removed {_describe_rule(rb)}"})
            elif rb != ra:
                deltas = [f"{k}: {rb.get(k)} → {ra.get(k)}"
                          for k in sorted(set(rb) | set(ra))
                          if k != "type" and rb.get(k) != ra.get(k)]
                rules.append({"kind": "changed", "rule_type": rb.get("type"),
                              "before": rb, "after": ra,
                              "text": f"{rb.get('type')} {', '.join(deltas)}"})

    summary = [r["text"] for r in rules]
    summary += [f"{f['field']}: {f['before']} → {f['after']}" for f in fields]
    return {"changed": bool(rules or fields), "rules": rules, "fields": fields,
            "summary": summary or ["No changes to the strategy definition."]}


def changelog(strategy: Optional[dict]) -> dict:
    """The strategy's history as a list of what actually changed at each step.

    Built by diffing consecutive stored snapshots and then the last snapshot
    against the live spec. Because it is derived, a version whose changes were
    never described still gets an accurate entry."""
    if not strategy:
        return {"available": False, "entries": [],
                "note": "Strategy not found."}
    versions = list(strategy.get("versions") or [])
    if not versions:
        return {"available": True, "entries": [], "versions": 0,
                "note": ("No edits recorded yet — this strategy has only ever been "
                         "saved once, so there is nothing to compare against.")}

    entries: list[dict] = []
    for i, v in enumerate(versions):
        prev = versions[i - 1]["spec"] if i else None
        if prev is None:
            entries.append({"v": v.get("v"), "at": v.get("at"), "name": v.get("name"),
                            "changes": ["Initial recorded version."], "detail": None})
            continue
        d = diff_specs(prev, v.get("spec"))
        entries.append({"v": v.get("v"), "at": v.get("at"), "name": v.get("name"),
                        "changes": d["summary"], "detail": d})

    # ...and the live spec, which is not itself a snapshot.
    d = diff_specs(versions[-1].get("spec"), strategy)
    entries.append({"v": "current", "at": strategy.get("updated_at"),
                    "name": strategy.get("name"),
                    "changes": d["summary"], "detail": d})
    return {"available": True, "entries": entries, "versions": len(versions)}


# --------------------------------------------------------------- permissions

def share_rank(role: Optional[str]) -> int:
    return _SHARE_RANK.get((role or "").strip().lower(), -1)


def share_can(role: Optional[str], capability: str) -> bool:
    """Default-deny: an unknown role or unknown capability permits nothing."""
    need = SHARE_CAPABILITIES.get(capability)
    if need is None:
        return False
    r, m = share_rank(role), share_rank(need)
    return r >= 0 and r >= m


class CollabStore:
    """Comments and per-strategy share grants, persisted as one JSON document."""

    def __init__(self, path: str):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text())
                if isinstance(d, dict):
                    d.setdefault("comments", {})
                    d.setdefault("shares", {})
                    return d
        except Exception:  # noqa: BLE001 — corrupt file behaves as empty
            pass
        return {"comments": {}, "shares": {}}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    # ----------------------------------------------------------- comments
    def add_comment(self, sid: str, *, author: str, body: str,
                    version: Optional[Any] = None,
                    reply_to: Optional[str] = None) -> dict:
        text = (body or "").strip()
        if not text:
            return {"error": "A comment needs some text."}
        data = self._load()
        rows = data["comments"].setdefault(sid, [])
        if reply_to and not any(c["id"] == reply_to for c in rows):
            return {"error": "The comment being replied to no longer exists."}
        c = {"id": uuid.uuid4().hex, "author": author, "body": text[:4000],
             "version": version, "reply_to": reply_to,
             "at": _now(), "edited_at": None}
        rows.append(c)
        self._write(data)
        return c

    def comments(self, sid: str, *, version: Optional[Any] = None) -> list[dict]:
        rows = list(self._load()["comments"].get(sid, []))
        if version is not None:
            rows = [c for c in rows if str(c.get("version")) == str(version)]
        return sorted(rows, key=lambda c: c.get("at", ""))

    def edit_comment(self, sid: str, comment_id: str, *, author: str,
                     body: str) -> Optional[dict]:
        """Only the author edits their own words. An edit is stamped, so a
        rewritten comment cannot pass as the original."""
        text = (body or "").strip()
        if not text:
            return {"error": "A comment needs some text."}
        data = self._load()
        for c in data["comments"].get(sid, []):
            if c["id"] == comment_id:
                if c["author"] != author:
                    return {"error": "You can only edit your own comments."}
                c["body"], c["edited_at"] = text[:4000], _now()
                self._write(data)
                return c
        return None

    def delete_comment(self, sid: str, comment_id: str, *, author: str) -> bool:
        data = self._load()
        rows = data["comments"].get(sid, [])
        for i, c in enumerate(rows):
            if c["id"] == comment_id:
                if c["author"] != author:
                    return False
                # Replies would otherwise dangle; mark rather than orphan them.
                if any(r.get("reply_to") == comment_id for r in rows):
                    c["body"], c["deleted"] = "[deleted]", True
                else:
                    rows.pop(i)
                self._write(data)
                return True
        return False

    # -------------------------------------------------------------- shares
    def share(self, sid: str, *, owner: str, user: str, role: str) -> dict:
        """Grant ``user`` a role on ``sid``. Only ``owner`` may grant, the role
        must be a share role (never an account role), and the owner cannot grant
        away their own strategy."""
        role = (role or "").strip().lower()
        if role not in SHARE_ROLES:
            return {"error": f"Role must be one of {', '.join(SHARE_ROLES)}."}
        if user == owner:
            return {"error": "You already own this strategy."}
        data = self._load()
        entry = data["shares"].setdefault(sid, {"owner": owner, "grants": {}})
        if entry.get("owner") != owner:
            return {"error": "Only the strategy's owner can share it."}
        entry["grants"][user] = {"role": role, "at": _now(), "by": owner}
        self._write(data)
        return {"strategy_id": sid, "owner": owner, "grants": entry["grants"]}

    def unshare(self, sid: str, *, owner: str, user: str) -> dict:
        data = self._load()
        entry = data["shares"].get(sid)
        if not entry or entry.get("owner") != owner:
            return {"error": "Only the strategy's owner can change sharing."}
        entry["grants"].pop(user, None)
        self._write(data)
        return {"strategy_id": sid, "owner": owner, "grants": entry["grants"]}

    def shares(self, sid: str) -> dict:
        entry = self._load()["shares"].get(sid)
        return {"strategy_id": sid, "owner": (entry or {}).get("owner"),
                "grants": (entry or {}).get("grants", {})}

    def role_for(self, sid: str, user: str) -> Optional[str]:
        """The caller's role on a strategy: ``"owner"`` for the owner, the
        granted share role for a collaborator, None for everyone else.

        A strategy with no share record returns None rather than a default — the
        caller decides what "unshared" means, and default-deny is the safe read
        for anything but the single-owner install."""
        entry = self._load()["shares"].get(sid)
        if not entry:
            return None
        if entry.get("owner") == user:
            return "owner"
        g = (entry.get("grants") or {}).get(user)
        return g.get("role") if g else None

    def can(self, sid: str, user: str, capability: str) -> bool:
        role = self.role_for(sid, user)
        if role == "owner":
            return True
        return share_can(role, capability)
