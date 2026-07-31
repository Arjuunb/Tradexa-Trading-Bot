#!/usr/bin/env python3
"""Generate the PrometheusRule CRD from the plain Prometheus rule file.

The same alerts have to reach two different consumers: a plain Prometheus in
the local compose stack, which reads rule files from disk, and the Prometheus
Operator in the cluster, which reads a PrometheusRule custom resource. Keeping
two hand-maintained copies of fifteen alert expressions guarantees they drift,
and the direction they drift is always the same — the local copy gets the fix
and production keeps the bug.

So there is one source of truth, deploy/observability/prometheus/rules/
hub-alerts.yml, and the CRD is generated from it.

    python deploy/scripts/gen_prometheusrule.py           # regenerate
    python deploy/scripts/gen_prometheusrule.py --check   # CI: fail on drift

The --check mode runs in CI, so editing one file and forgetting the other
fails the build instead of silently shipping.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "deploy/observability/prometheus/rules/hub-alerts.yml"
TARGET = REPO / "deploy/k8s/base/prometheusrule.yaml"

HEADER = """# GENERATED FILE — DO NOT EDIT.
#
# Source:    deploy/observability/prometheus/rules/hub-alerts.yml
# Regenerate: python deploy/scripts/gen_prometheusrule.py
#
# Edit the source file and re-run the generator. CI runs this script with
# --check, so hand-editing this file fails the build.
"""


def build() -> str:
    groups = yaml.safe_load(SOURCE.read_text())["groups"]
    doc = {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "PrometheusRule",
        "metadata": {
            "name": "tradexa-hub-alerts",
            "namespace": "tradexa",
            "labels": {
                "app.kubernetes.io/name": "tradexa-hub",
                # Must match the Prometheus resource's `ruleSelector`, or the
                # rules load into no Prometheus at all and nothing reports it.
                "release": "kube-prometheus-stack",
            },
        },
        "spec": {"groups": groups},
    }
    body = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, width=100)
    return HEADER + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the generated file is out of date")
    args = ap.parse_args()

    generated = build()
    if args.check:
        current = TARGET.read_text() if TARGET.exists() else ""
        if current != generated:
            print(f"{TARGET.relative_to(REPO)} is out of date with "
                  f"{SOURCE.relative_to(REPO)}.\n"
                  "Run: python deploy/scripts/gen_prometheusrule.py",
                  file=sys.stderr)
            return 1
        print(f"{TARGET.relative_to(REPO)} is up to date")
        return 0

    TARGET.write_text(generated)
    n = sum(len(g["rules"]) for g in yaml.safe_load(SOURCE.read_text())["groups"])
    print(f"wrote {TARGET.relative_to(REPO)} ({n} alerts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
