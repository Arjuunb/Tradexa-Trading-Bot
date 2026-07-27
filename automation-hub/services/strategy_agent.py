"""AI Strategy Agent — plain English -> the engine's executable strategy spec.

This is an INTERPRETER, never a generator. Its contract:

  * it may only emit rule types the engine actually implements (the grammar is
    derived from services.strategy_builder.CATEGORIES, which the existing test
    suite already pins 1:1 to strategies.custom._rule — so the agent's
    vocabulary can never drift from the engine's);
  * every emitted rule must be GROUNDED — it carries the user's own phrase that
    produced it. Ungrounded rules are rejected, not kept;
  * anything ambiguous becomes a clarification QUESTION, never an assumption;
  * anything the engine cannot express becomes an explicit UNSUPPORTED entry,
    never a silent drop and never a stub.

The natural-language step needs an LLM. This repo has none today, so the call
sits behind a seam and degrades the way the rest of the app does — an honest
``{"available": false, "note": ...}`` — rather than falling back to keyword
matching and pretending it understood the user.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from services.strategy_builder import CATEGORIES, CONFIG

# --------------------------------------------------------------------- grammar

def rule_grammar() -> dict[str, dict]:
    """{rule_type: {label, params: {name: {default, options}}}} straight from the
    builder palette, so the agent can only speak the engine's language."""
    out: dict[str, dict] = {}
    for cat in CATEGORIES:
        for blk in cat["blocks"]:
            params = {}
            for p in blk.get("params", []):
                params[p["name"]] = {"default": p.get("default"),
                                     "options": p.get("options")}
            out[blk["type"]] = {"label": blk["label"], "category": cat["key"],
                                "desc": blk.get("desc", ""), "params": params}
    return out


def rule_types() -> set[str]:
    return set(rule_grammar())


# ------------------------------------------------------- engine capability gaps
# Things a trader may reasonably ask for that the CURRENT spec cannot express.
# Surfaced explicitly so the agent never silently drops or fakes them.

_UNSUPPORTED_PATTERNS: list[tuple[str, str, str]] = [
    (r"\b(news|nfp|fomc|cpi|economic calendar|high[- ]impact)\b",
     "News / economic-calendar filtering",
     "There is no news or economic-calendar data source in the platform, so this "
     "rule cannot be enforced. Remove it, or run the strategy and avoid news "
     "windows manually."),
    (r"\b(twitter|reddit|sentiment|social)\b",
     "Social / sentiment filtering",
     "No social-sentiment feed is wired into the strategy engine."),
    (r"\b(order ?flow|footprint|delta|depth of market|dom|level ?2)\b",
     "Order-flow / market-depth rules",
     "The engine trades on OHLCV candles; order-flow data is not available."),
    (r"\b(options?|gamma|open interest|funding rate)\b",
     "Derivatives-data rules",
     "Options / funding data is not part of the strategy engine's inputs."),
]

_SESSION_WORDS = {"london": "london", "new york": "new_york", "newyork": "new_york",
                  "ny": "new_york", "tokyo": "tokyo", "asian": "tokyo",
                  "asia": "tokyo", "sydney": "sydney"}


def detect_unsupported(text: str) -> list[dict]:
    """Deterministic pre-scan of the user's text for asks the engine can't honour.

    Runs BEFORE any model call, so these are reported even when no LLM is
    configured — and they are reported as gaps, never quietly ignored."""
    low = (text or "").lower()
    found: list[dict] = []
    for pattern, title, why in _UNSUPPORTED_PATTERNS:
        m = re.search(pattern, low)
        if m:
            found.append({"phrase": m.group(0), "capability": title, "why": why})

    # The spec holds exactly ONE session window ({start, end}, start <= h < end),
    # so two disjoint sessions cannot be represented, and a wrap-around window
    # (e.g. 21->6) never matches. Both must be raised, not merged by assumption.
    named = {v for k, v in _SESSION_WORDS.items() if re.search(rf"\b{k}\b", low)}
    if len(named) > 1:
        found.append({
            "phrase": ", ".join(sorted(named)),
            "capability": "Multiple trading sessions",
            "why": "A strategy carries a single session window, so several separate "
                   "sessions cannot be combined. Pick one session, or widen it to a "
                   "single window that covers the hours you want.",
        })
    return found


# ------------------------------------------------------------------- validation

_REQUIRED = ("name", "symbol", "timeframe", "side", "entry", "stop", "target",
             "risk_per_trade_pct")


def _walk_rules(node: Any):
    """Yield every leaf rule in an entry/exit condition tree (groups recurse)."""
    if not isinstance(node, dict):
        return
    for r in node.get("rules") or []:
        if isinstance(r, dict) and r.get("rules") is not None and r.get("type") is None:
            yield from _walk_rules(r)
        elif isinstance(r, dict):
            yield r


def validate_spec(spec: dict) -> dict:
    """Strict structural validation of a compiled spec.

    The engine has NO schema validator — an unknown rule type silently never
    fires (strategies.custom._rule falls through to False). That failure mode is
    unacceptable for generated specs, so this catches it loudly."""
    errors: list[str] = []
    warnings: list[str] = []
    grammar = rule_grammar()

    for key in _REQUIRED:
        if spec.get(key) in (None, ""):
            errors.append(f"Missing required field: {key}")

    side = spec.get("side")
    if side not in (None, "long", "short"):
        errors.append(f"side must be 'long' or 'short' (got {side!r})")

    entry = spec.get("entry") or {}
    leaves = list(_walk_rules(entry))
    if not leaves:
        errors.append("No entry rules — the strategy would never take a trade.")
    for r in leaves:
        rtype = r.get("type")
        if rtype not in grammar:
            errors.append(f"Unknown rule type {rtype!r} — the engine does not implement it.")
            continue
        for pname, pval in r.items():
            if pname in ("type", "negate", "source"):
                continue
            meta = grammar[rtype]["params"].get(pname)
            if meta is None:
                warnings.append(f"{rtype}: unknown parameter {pname!r} (ignored by the engine)")
                continue
            opts = meta.get("options")
            if opts and pval not in opts:
                errors.append(f"{rtype}.{pname} must be one of {opts} (got {pval!r})")
        # grounding: every rule must trace back to the user's words
        if not str(r.get("source") or "").strip():
            errors.append(f"{rtype}: not grounded in the strategy text (no source phrase).")

    stop = spec.get("stop") or {}
    if stop and stop.get("type") not in (None, "atr", "pct"):
        errors.append(f"stop.type must be 'atr' or 'pct' (got {stop.get('type')!r})")
    target = spec.get("target") or {}
    if target and target.get("type") not in (None, "rr", "pct"):
        errors.append(f"target.type must be 'rr' or 'pct' (got {target.get('type')!r})")

    risk = spec.get("risk_per_trade_pct")
    if isinstance(risk, (int, float)):
        if risk <= 0:
            errors.append("risk_per_trade_pct must be greater than 0.")
        elif risk > 0.05:
            warnings.append(f"Risking {risk * 100:.1f}% per trade is aggressive.")

    sess = spec.get("session")
    if isinstance(sess, dict):
        s, e = sess.get("start"), sess.get("end")
        if isinstance(s, int) and isinstance(e, int) and s >= e:
            errors.append("session start must be before end — a wrap-around window "
                          "(e.g. 21:00 to 06:00) is not supported by the engine.")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ----------------------------------------------------------------- completeness

_SCORED = (
    ("entry", "Entry rules", lambda s: bool(list(_walk_rules(s.get("entry") or {})))),
    ("stop", "Stop loss", lambda s: bool(s.get("stop"))),
    ("target", "Take profit", lambda s: bool(s.get("target"))),
    ("risk_per_trade_pct", "Position sizing / risk", lambda s: bool(s.get("risk_per_trade_pct"))),
    ("symbol", "Asset", lambda s: bool(s.get("symbol"))),
    ("timeframe", "Timeframe", lambda s: bool(s.get("timeframe"))),
    ("side", "Direction", lambda s: s.get("side") in ("long", "short")),
    ("session", "Trading session", lambda s: s.get("session") is not None),
)


def completeness(spec: dict) -> dict:
    """Completeness score + which parts are still missing (drives the UI panel)."""
    present, missing = [], []
    for key, label, check in _SCORED:
        (present if check(spec) else missing).append(label)
    score = round(100 * len(present) / len(_SCORED))
    return {"score": score, "present": present, "missing": missing,
            "rule_count": len(list(_walk_rules(spec.get("entry") or {})))}


# ---------------------------------------------------------------- clarification

def clarifying_questions(spec: dict, validation: dict) -> list[dict]:
    """Turn gaps and errors into concrete questions with choosable options.

    Never guesses a default — compilation is expected to PAUSE on these."""
    qs: list[dict] = []
    if not spec.get("stop"):
        qs.append({"id": "stop", "question": "How should the stop loss be placed?",
                   "options": ["ATR-based (1.5x ATR-14)", "Fixed percentage",
                               "Below the previous swing low"]})
    if not spec.get("target"):
        qs.append({"id": "target", "question": "How should the take profit be set?",
                   "options": ["Risk/reward multiple (e.g. 1:3)", "Fixed percentage"]})
    if not spec.get("risk_per_trade_pct"):
        qs.append({"id": "risk", "question": "How much of the account should each trade risk?",
                   "options": ["0.5%", "1%", "2%"]})
    if spec.get("side") not in ("long", "short"):
        qs.append({"id": "side", "question": "Should this strategy trade long, short, or both?",
                   "options": ["Long only", "Short only"]})
    if not spec.get("timeframe"):
        qs.append({"id": "timeframe", "question": "Which timeframe should it execute on?",
                   "options": ["5m", "15m", "1h", "4h", "1d"]})
    if not spec.get("symbol"):
        qs.append({"id": "symbol", "question": "Which asset should it trade?",
                   "options": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]})
    for err in validation.get("errors", []):
        if "not grounded" in err:
            qs.append({"id": "grounding", "question":
                       f"A rule could not be traced to your description ({err.split(':')[0]}). "
                       "Please restate that condition.", "options": []})
    return qs


# ------------------------------------------------------------------- LLM seam

_KEY_ENVS = ("HUB_LLM_API_KEY", "ANTHROPIC_API_KEY")
_MODEL = os.environ.get("HUB_LLM_MODEL", "claude-sonnet-4-5")
_API_URL = "https://api.anthropic.com/v1/messages"


def llm_available() -> bool:
    return bool(_api_key())


def _api_key() -> Optional[str]:
    for env in _KEY_ENVS:
        v = os.environ.get(env, "").strip()
        if v:
            return v
    return None


def _system_prompt() -> str:
    """Built FROM the grammar, so the model is shown only real rule types."""
    g = rule_grammar()
    lines = []
    for rtype, meta in sorted(g.items()):
        params = ", ".join(
            f"{p}({'|'.join(map(str, d['options'])) if d.get('options') else d.get('default')})"
            for p, d in meta["params"].items())
        lines.append(f"- {rtype}: {meta['desc']} params: {params or 'none'}")
    sessions = ", ".join(f"{s['key']}({s['start']}-{s['end']})"
                         for s in CONFIG.get("sessions", []))
    return (
        "You convert a trader's plain-English strategy into a strict JSON spec. "
        "You are an interpreter, NOT a strategy designer.\n\n"
        "HARD RULES:\n"
        "1. Only use the rule types listed below. Never invent a type or parameter.\n"
        "2. Never add a rule the user did not describe. Never fill in a missing "
        "rule with a sensible default — omit it instead.\n"
        "3. Every rule MUST include a \"source\" field quoting the user's own words "
        "that produced it. If you cannot quote it, do not emit the rule.\n"
        "4. If something is ambiguous, omit it and add a question to \"questions\".\n"
        "5. Output JSON only, no prose.\n\n"
        f"RULE TYPES:\n" + "\n".join(lines) + "\n\n"
        f"SESSIONS (single window only): {sessions}\n"
        "stop: {type:'atr',mult,period} or {type:'pct',pct}\n"
        "target: {type:'rr',rr} or {type:'pct',pct}\n\n"
        "OUTPUT SHAPE:\n"
        '{"spec": {"name","symbol","timeframe","side","entry":{"op":"AND|OR",'
        '"rules":[{"type",...,"source"}]},"stop":{},"target":{},'
        '"risk_per_trade_pct",...}, "questions":[{"id","question","options":[]}], '
        '"notes":[]}'
    )


def _call_llm(text: str, answers: Optional[dict] = None, timeout: float = 60.0) -> dict:
    """POST to the Anthropic Messages API using stdlib-adjacent ``requests``
    (already a dependency) — no new SDK is added to the deploy."""
    import requests

    user = text if not answers else (
        text + "\n\nClarifications the user provided:\n"
        + "\n".join(f"- {k}: {v}" for k, v in answers.items()))
    resp = requests.post(
        _API_URL,
        headers={"x-api-key": _api_key(), "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": _MODEL, "max_tokens": 4000,
              "system": _system_prompt(),
              "messages": [{"role": "user", "content": user}]},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    parts = [b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"]
    raw = "".join(parts).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", raw).strip()
    return json.loads(raw)


# -------------------------------------------------------------------- compile

def compile_strategy(text: str, answers: Optional[dict] = None) -> dict:
    """Interpret ``text`` into a validated spec.

    Always returns the deterministic parts (unsupported-capability scan) even
    when no LLM is configured, so the user still learns what the engine cannot
    do. Never returns a spec it could not ground and validate."""
    text = (text or "").strip()
    unsupported = detect_unsupported(text)
    if not text:
        return {"available": True, "spec": None, "questions": [], "errors": [],
                "warnings": [], "unsupported": unsupported, "completeness": None,
                "note": "Describe your strategy to begin."}

    if not llm_available():
        return {
            "available": False, "spec": None, "questions": [], "errors": [],
            "warnings": [], "unsupported": unsupported, "completeness": None,
            "note": "AI Strategy Agent unavailable — no LLM API key configured. "
                    "Set HUB_LLM_API_KEY (or ANTHROPIC_API_KEY) to enable natural-"
                    "language compilation. The visual Strategy Builder still works.",
        }

    try:
        out = _call_llm(text, answers)
    except Exception as e:  # noqa: BLE001 — an interpreter failure must never fabricate
        return {"available": True, "spec": None, "questions": [], "errors": [],
                "warnings": [], "unsupported": unsupported, "completeness": None,
                "note": f"Could not interpret the strategy ({type(e).__name__}). "
                        "Nothing was compiled — please retry or rephrase."}

    spec = out.get("spec") or None
    questions = list(out.get("questions") or [])
    notes = list(out.get("notes") or [])
    if not isinstance(spec, dict):
        return {"available": True, "spec": None, "questions": questions, "errors": [],
                "warnings": [], "unsupported": unsupported, "completeness": None,
                "note": "The description did not contain enough to compile a strategy."}

    validation = validate_spec(spec)
    questions += clarifying_questions(spec, validation)
    # de-dup questions by id, preserving order
    seen, uniq = set(), []
    for q in questions:
        if q.get("id") in seen:
            continue
        seen.add(q.get("id"))
        uniq.append(q)

    return {
        "available": True,
        "spec": spec,
        "compiled": validation["ok"] and not uniq,
        "errors": validation["errors"],
        "warnings": validation["warnings"],
        "questions": uniq,
        "unsupported": unsupported,
        "completeness": completeness(spec),
        "notes": notes,
    }
