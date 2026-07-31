#!/usr/bin/env bash
#
# Post-deploy smoke test. Run against a live base URL:
#
#     ./deploy/scripts/smoke_test.sh https://staging.trade-logx.com
#
# Deliberately shallow and fast. This is not a test suite — it answers one
# question: "did the thing that just deployed come up correctly?" Anything
# slower than about thirty seconds will be skipped under pressure, which is
# exactly when it matters most.
#
# Exits non-zero on the first failure so CD rolls back.

set -euo pipefail

BASE="${1:-}"
if [ -z "$BASE" ]; then
  echo "usage: $0 <base-url>" >&2
  exit 2
fi
BASE="${BASE%/}"

pass=0
fail=0

# Retries: a rollout can complete moments before the load balancer has finished
# converging, and failing on that races the platform rather than the deploy.
CURL=(curl -fsS --max-time 15 --retry 3 --retry-delay 2 --retry-connrefused)

check_status() {
  local path="$1" expected="${2:-200}"
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
         --retry 3 --retry-delay 2 --retry-connrefused "${BASE}${path}" || echo 000)
  if [ "$code" = "$expected" ]; then
    printf '  ok    %-24s %s\n' "$path" "$code"; pass=$((pass + 1))
  else
    printf '  FAIL  %-24s %s (expected %s)\n' "$path" "$code" "$expected" >&2
    fail=$((fail + 1))
  fi
}

check_contains() {
  local path="$1" needle="$2"
  if "${CURL[@]}" "${BASE}${path}" 2>/dev/null | grep -q -- "$needle"; then
    printf '  ok    %-24s contains %s\n' "$path" "$needle"; pass=$((pass + 1))
  else
    printf '  FAIL  %-24s missing %s\n' "$path" "$needle" >&2
    fail=$((fail + 1))
  fi
}

echo "smoke testing ${BASE}"

echo "health:"
check_status  /health/live
check_status  /health/ready
check_status  /health/startup
check_contains /health/live alive
# Readiness reporting 200 is the real gate: it means every dependency check
# registered at startup passed, not merely that the process is answering.
check_contains /health/ready '"status": "ready"'

echo "identity:"
check_status   /version
check_contains /version commit

echo "public routes:"
# Every one is in the sitemap and served by the SPA fallback. They have
# regressed before — client-side navigation kept working while a hard load or a
# crawler visit got the API's 404 JSON, so the breakage was invisible to anyone
# already on the site and total for anyone arriving from a search result.
for p in / /features /engine /live-trade /selectivity /how-it-works /security \
         /performance /dashboard /docs /api /sdks /open-source /github \
         /support /community /status /privacy /terms /risk-disclosure; do
  check_status "$p"
done

echo "crawler files:"
check_status /robots.txt
check_status /sitemap.xml

echo "api:"
check_status /api/v1
check_status /api/v1/docs
# The versioned API subtree must stay session-gated. If this returns 200 the
# auth wall has a hole in it — the landing pages are exempted by EXACT match
# precisely so that "/api" as a page cannot unlock the "/api/v1/*" subtree.
check_status /api/v1/ai/insights 401

echo
echo "passed: ${pass}   failed: ${fail}"
[ "$fail" -eq 0 ] || exit 1
echo "smoke test OK"
