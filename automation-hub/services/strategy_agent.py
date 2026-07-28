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


# Risk is a FRACTION of equity (0.01 = 1%). At or above this it is almost
# certainly a percentage written as a whole number, since risking a quarter of
# the account on one trade is not something people mention in passing.
RISK_UNIT_AMBIGUOUS = 0.25
RISK_AGGRESSIVE = 0.05


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
        elif risk > 1:
            errors.append(
                f"risk_per_trade_pct is {risk} — it is a FRACTION of equity, so it "
                "cannot exceed 1 (100%). Write 1% as 0.01.")
        elif risk >= RISK_UNIT_AMBIGUOUS:
            # "Risk 1% per trade" arriving as 1 instead of 0.01 reads as risking
            # the ENTIRE account. Nobody writing a strategy in prose means that,
            # but the two are indistinguishable from the number alone — so this
            # blocks rather than guessing, and it is never silently rescaled.
            # Quietly dividing by 100 would be the interpreter rewriting the
            # user's risk, which is exactly what it must not do.
            errors.append(
                f"risk_per_trade_pct is {risk}, which the engine reads as "
                f"{risk * 100:.0f}% of equity per trade. If you meant "
                f"{risk:.0f}%, it should be {risk / 100:g}. Confirm which you want.")
        elif risk > RISK_AGGRESSIVE:
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

def clarifying_questions(spec: dict, validation: dict,
                         existing: Optional[list[dict]] = None) -> list[dict]:
    """Turn gaps and errors into concrete questions with choosable options.

    Never guesses a default — compilation is expected to PAUSE on these. When
    the LLM has already raised a question about a topic (it does this for an
    unsupported request like "below the previous swing low"), the matching
    deterministic question is suppressed: two stop questions side by side, one
    of them offering the very option the other calls unsupported, is worse than
    silence."""
    # Topics the model already asked about — matched on id or on the question
    # text, since the model's ids are not under our control.
    covered = set()
    for q in existing or []:
        blob = f"{q.get('id', '')} {q.get('question', '')}".lower()
        for topic in ("stop", "target", "take profit", "risk", "side",
                      "long", "short", "timeframe", "symbol", "asset"):
            if topic in blob:
                covered.add("target" if topic == "take profit" else
                            "side" if topic in ("long", "short") else
                            "symbol" if topic == "asset" else topic)

    qs: list[dict] = []
    if not spec.get("stop") and "stop" not in covered:
        # NOTE: only atr and pct are choosable — "below the previous swing low"
        # is deliberately absent because the engine cannot express it, and
        # offering an option that fails validation on selection is a trap.
        qs.append({"id": "stop", "question": "How should the stop loss be placed?",
                   "options": ["ATR-based (1.5x ATR-14)", "Fixed percentage (e.g. 2%)"]})
    if not spec.get("target") and "target" not in covered:
        qs.append({"id": "target", "question": "How should the take profit be set?",
                   "options": ["Risk/reward multiple (e.g. 1:3)", "Fixed percentage"]})
    if not spec.get("risk_per_trade_pct") and "risk" not in covered:
        qs.append({"id": "risk", "question": "How much of the account should each trade risk?",
                   "options": ["0.5%", "1%", "2%"]})
    if spec.get("side") not in ("long", "short") and "side" not in covered:
        qs.append({"id": "side", "question": "Should this strategy trade long, short, or both?",
                   "options": ["Long only", "Short only"]})
    if not spec.get("timeframe") and "timeframe" not in covered:
        qs.append({"id": "timeframe", "question": "Which timeframe should it execute on?",
                   "options": ["5m", "15m", "1h", "4h", "1d"]})
    if not spec.get("symbol") and "symbol" not in covered:
        qs.append({"id": "symbol", "question": "Which asset should it trade?",
                   "options": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]})
    for err in validation.get("errors", []):
        if "not grounded" in err:
            qs.append({"id": "grounding", "question":
                       f"A rule could not be traced to your description ({err.split(':')[0]}). "
                       "Please restate that condition.", "options": []})
    return qs


def risk_unit_questions(spec: dict, validation: dict) -> list[dict]:
    """Ask which risk figure was meant when the units are ambiguous.

    Split out from ``clarifying_questions`` because it fires on a value that IS
    present rather than one that is missing. Without it the blocking error has
    no answerable question attached, and the user is told compilation is paused
    with no control that resumes it.
    """
    risk = spec.get("risk_per_trade_pct")
    if not isinstance(risk, (int, float)) or not (0 < risk <= 1):
        return []
    if risk < RISK_UNIT_AMBIGUOUS:
        return []
    return [{
        "id": "risk_units",
        "question": (f"Risk was read as {risk}, which is {risk * 100:.0f}% of the "
                     f"account per trade. Did you mean {risk:.0f}%?"),
        "options": [f"{risk:.0f}% per trade (use {risk / 100:g})",
                    f"Yes — really risk {risk * 100:.0f}% per trade"],
    }]


# ------------------------------------------------------------------- LLM seam

_KEY_ENVS = ("HUB_LLM_API_KEY", "ANTHROPIC_API_KEY")
_MODEL = os.environ.get("HUB_LLM_MODEL", "claude-opus-5")


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
        "target: {type:'rr',rr} or {type:'pct',pct}\n"
        # Spelled out because the field NAME ends in _pct while the VALUE is a
        # fraction. Emitting 1 for "risk 1%" reads downstream as risking the
        # whole account, and the number alone cannot be told apart from someone
        # genuinely meaning 100%.
        "risk_per_trade_pct: a FRACTION of equity, NOT a percentage number. "
        "\"risk 1%\" -> 0.01. \"risk 0.5% per trade\" -> 0.005. \"2 percent\" -> 0.02. "
        "Never emit 1 for 1% — 1 means 100% of the account on a single trade.\n\n"
        "OUTPUT SHAPE:\n"
        '{"spec": {"name","symbol","timeframe","side","entry":{"op":"AND|OR",'
        '"rules":[{"type",...,"source"}]},"stop":{},"target":{},'
        '"risk_per_trade_pct",...}, "questions":[{"id","question","options":[]}], '
        '"notes":[]}'
    )


def _call_llm(text: str, answers: Optional[dict] = None, timeout: float = 120.0) -> dict:
    """Interpret the description via the Anthropic Messages API.

    Uses the official SDK rather than hand-rolled HTTP: it carries the typed
    error classes this module needs to tell a bad key from an exhausted balance,
    and it retries transient failures on its own."""
    import anthropic

    user = text if not answers else (
        text + "\n\nClarifications the user provided:\n"
        + "\n".join(f"- {k}: {v}" for k, v in answers.items()))

    client = anthropic.Anthropic(api_key=_api_key(), timeout=timeout)
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=4000,
        system=_system_prompt(),
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", raw).strip()
    return json.loads(raw)


def describe_llm_error(exc: BaseException) -> str:
    """A sentence a user can act on, instead of an exception class name.

    The previous handler rendered every failure as its class — "HTTPError" —
    which reads identically for an invalid key, an exhausted balance, and a rate
    limit. Those need three different actions, so the status and the API's own
    message have to survive."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover - the SDK is a hard dependency
        return f"{type(exc).__name__}: {exc}"

    detail = getattr(exc, "message", None) or str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return ("The API key was rejected (401). Check HUB_LLM_API_KEY is the "
                f"full key and has not been revoked. API said: {detail}")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return f"The API key lacks access to {_MODEL} (403). API said: {detail}"
    if isinstance(exc, anthropic.NotFoundError):
        return (f"Model '{_MODEL}' was not found (404). Set HUB_LLM_MODEL to a "
                f"current model id. API said: {detail}")
    if isinstance(exc, anthropic.RateLimitError):
        return f"Rate limited (429) — retry shortly. API said: {detail}"
    if isinstance(exc, anthropic.BadRequestError):
        # The most common one in practice: a valid key on an account with no
        # credit. The API returns 400, so without the message it is invisible.
        return f"The request was rejected (400). API said: {detail}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"API error {exc.status_code}. API said: {detail}"
    if isinstance(exc, anthropic.APIConnectionError):
        return ("Could not reach the Anthropic API — check the host's outbound "
                f"network. Detail: {detail}")
    if isinstance(exc, json.JSONDecodeError):
        return "The model's reply was not valid JSON, so nothing was compiled."
    return f"{type(exc).__name__}: {detail}"


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
                "note": f"Could not interpret the strategy. {describe_llm_error(e)} "
                        "Nothing was compiled."}

    spec = out.get("spec") or None
    questions = list(out.get("questions") or [])
    notes = list(out.get("notes") or [])
    if not isinstance(spec, dict):
        return {"available": True, "spec": None, "questions": questions, "errors": [],
                "warnings": [], "unsupported": unsupported, "completeness": None,
                "note": "The description did not contain enough to compile a strategy."}

    validation = validate_spec(spec)
    questions += clarifying_questions(spec, validation, existing=questions)
    questions += risk_unit_questions(spec, validation)
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
