"""Container healthcheck probe.

A standalone script rather than an inline ``python -c`` in the Dockerfile: the
one-liner needed to read $PORT and build a URL turns into an unreadable mess of
nested quoting inside a HEALTHCHECK instruction, and an unreadable healthcheck
is one nobody ever fixes when it silently starts passing on everything.

Probes ``/health/live`` — liveness, not ``/health``. The distinction is the
whole point: ``/health`` queries Supabase and the persistence tier, so wiring a
restart trigger to it means an upstream blip kills a process that is running
fine, turning a degraded dependency into an outage. See ops/health.py.

Exit 0 = healthy, 1 = not.
"""
from __future__ import annotations

import os
import sys
import urllib.request


def main() -> int:
    port = os.environ.get("PORT", "8000")
    url = f"http://127.0.0.1:{port}/health/live"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310 - fixed localhost URL
            return 0 if resp.status == 200 else 1
    except Exception as exc:  # noqa: BLE001
        print(f"healthcheck failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
