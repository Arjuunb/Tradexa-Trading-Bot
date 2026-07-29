"""Tradexa — the trading system's architectural core.

This package is the destination of an incremental Clean Architecture
consolidation, not a rewrite. The engine in ``bot/`` and the services in
``automation-hub/`` are live, deployed and covered by ~1400 tests; replacing
them wholesale would trade working behaviour for a tidier import graph.

So ``tradexa`` grows in layers instead:

    tradexa.core.models       domain types (extends bot.types, never forks it)
    tradexa.core.exceptions   the error taxonomy
    tradexa.core.interfaces   ports the domain depends on
    tradexa.core.events       the internal event vocabulary

Dependency rule: nothing under ``tradexa.core`` may import FastAPI, sqlite3,
ccxt, requests, or any other I/O library. A test enforces this — see
``tests/test_core_architecture.py``. Infrastructure implements these
interfaces from the outside; the domain never reaches out to it.
"""
