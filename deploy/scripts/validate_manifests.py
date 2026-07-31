#!/usr/bin/env python3
"""Assert the invariants that keep this deployment safe.

Run against the RENDERED output of each overlay, not the source files: an
overlay patch can undo anything the base sets, so checking the base proves
nothing about what actually reaches the cluster.

    python deploy/scripts/validate_manifests.py                    # all overlays
    python deploy/scripts/validate_manifests.py --overlay staging

Two classes of check:

**Safety** — the single-engine guarantee. The engine must be a StatefulSet of
exactly one with the singleton lease enabled, and nothing may autoscale it.
Getting this wrong means two trading engines against one account, which is the
worst failure this system has. It is checked mechanically because it is exactly
the kind of thing a hurried patch silently breaks.

**Hardening** — non-root, read-only root filesystem, no privilege escalation,
all capabilities dropped, seccomp, no API token, resource requests, and the
three distinct probes. Individually unremarkable; collectively the difference
between a container escape being contained and being the whole cluster.

Set KUSTOMIZE to point at the binary if it is not on PATH.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
OVERLAYS = REPO / "deploy/k8s/overlays"

# Workload kinds that carry a pod template.
POD_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}

failures: list[str] = []
checks_run = 0


def fail(msg: str) -> None:
    failures.append(msg)


def check(cond: bool, msg: str) -> None:
    global checks_run
    checks_run += 1
    if not cond:
        fail(msg)


def kustomize_bin() -> str:
    binary = os.environ.get("KUSTOMIZE") or shutil.which("kustomize")
    if not binary:
        print("kustomize not found. Install it, or set KUSTOMIZE=/path/to/kustomize",
              file=sys.stderr)
        sys.exit(2)
    return binary


def render(overlay: str) -> list[dict]:
    out = subprocess.run(
        [kustomize_bin(), "build", str(OVERLAYS / overlay)],
        capture_output=True, text=True, check=False)
    if out.returncode != 0:
        print(f"kustomize build failed for {overlay}:\n{out.stderr}", file=sys.stderr)
        sys.exit(2)
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def pod_specs(docs: list[dict]):
    """Yield (description, podSpec) for every pod template, including the one
    buried two levels down inside a CronJob."""
    for d in docs:
        kind, name = d.get("kind"), d.get("metadata", {}).get("name", "?")
        if kind in POD_KINDS:
            yield f"{kind}/{name}", d["spec"]["template"]["spec"]
        elif kind == "CronJob":
            yield (f"CronJob/{name}",
                   d["spec"]["jobTemplate"]["spec"]["template"]["spec"])


def validate(overlay: str) -> None:
    docs = render(overlay)
    by_kind: dict[str, list[dict]] = {}
    for d in docs:
        by_kind.setdefault(d["kind"], []).append(d)
    tag = f"[{overlay}]"

    # ── the single-engine guarantee ───────────────────────────────────────
    engines = [d for d in by_kind.get("StatefulSet", [])
               if "engine" in d["metadata"]["name"]]
    check(len(engines) == 1, f"{tag} expected exactly one engine StatefulSet, found {len(engines)}")
    for eng in engines:
        name = eng["metadata"]["name"]
        check(eng["spec"]["replicas"] == 1,
              f"{tag} {name} has replicas={eng['spec']['replicas']} — MUST be 1. "
              "Two engines against one account is duplicate order flow.")
        env = {e["name"]: e.get("value") for e in
               eng["spec"]["template"]["spec"]["containers"][0].get("env", [])}
        check(env.get("HUB_ROLE") == "engine", f"{tag} {name} HUB_ROLE must be 'engine'")
        check(env.get("HUB_SINGLETON_LEASE") == "1",
              f"{tag} {name} must set HUB_SINGLETON_LEASE=1 — the lease is the "
              "last defence against a second engine")

    # The engine must never be an autoscaling target.
    for hpa in by_kind.get("HorizontalPodAutoscaler", []):
        ref = hpa["spec"]["scaleTargetRef"]
        check("engine" not in ref["name"],
              f"{tag} HPA {hpa['metadata']['name']} targets the engine — "
              "scaling the engine is never correct")
        check(ref["kind"] == "Deployment",
              f"{tag} HPA {hpa['metadata']['name']} should target a Deployment, got {ref['kind']}")

    # Web pods must NOT start workers.
    for dep in by_kind.get("Deployment", []):
        if "web" not in dep["metadata"]["name"]:
            continue
        env = {e["name"]: e.get("value") for e in
               dep["spec"]["template"]["spec"]["containers"][0].get("env", [])}
        check(env.get("HUB_ROLE") == "web",
              f"{tag} {dep['metadata']['name']} HUB_ROLE must be 'web' so it starts no "
              "singleton workers")

    # ── hardening, applied to every pod ───────────────────────────────────
    for desc, spec in pod_specs(docs):
        sc = spec.get("securityContext", {})
        check(sc.get("runAsNonRoot") is True, f"{tag} {desc}: runAsNonRoot must be true")
        check(sc.get("runAsUser", 0) != 0, f"{tag} {desc}: must not run as uid 0")
        check(sc.get("seccompProfile", {}).get("type") == "RuntimeDefault",
              f"{tag} {desc}: seccompProfile must be RuntimeDefault")
        check(spec.get("automountServiceAccountToken") is False,
              f"{tag} {desc}: automountServiceAccountToken must be false — the app "
              "never calls the Kubernetes API")

        for c in spec["containers"]:
            cd = f"{desc}/{c['name']}"
            csc = c.get("securityContext", {})
            check(csc.get("allowPrivilegeEscalation") is False,
                  f"{tag} {cd}: allowPrivilegeEscalation must be false")
            check(csc.get("readOnlyRootFilesystem") is True,
                  f"{tag} {cd}: readOnlyRootFilesystem must be true")
            check(csc.get("capabilities", {}).get("drop") == ["ALL"],
                  f"{tag} {cd}: must drop ALL capabilities")

            res = c.get("resources", {})
            check("cpu" in res.get("requests", {}) and "memory" in res.get("requests", {}),
                  f"{tag} {cd}: must declare cpu and memory requests — without them the "
                  "scheduler cannot place the pod safely and it is first to be evicted")
            check("memory" in res.get("limits", {}),
                  f"{tag} {cd}: must declare a memory limit")

            # Probes only apply to the long-running servers, not batch jobs.
            if desc.startswith(("Deployment/", "StatefulSet/")):
                for probe in ("startupProbe", "livenessProbe", "readinessProbe"):
                    check(probe in c, f"{tag} {cd}: missing {probe}")
                if "livenessProbe" in c:
                    path = c["livenessProbe"].get("httpGet", {}).get("path")
                    check(path == "/health/live",
                          f"{tag} {cd}: liveness must probe /health/live, not {path!r}. "
                          "/health touches Supabase, so using it restarts healthy pods "
                          "whenever a dependency blips.")
                if "readinessProbe" in c:
                    path = c["readinessProbe"].get("httpGet", {}).get("path")
                    check(path == "/health/ready",
                          f"{tag} {cd}: readiness must probe /health/ready, not {path!r}")

    # ── config wiring ─────────────────────────────────────────────────────
    # The generated ConfigMap carries a content hash, and every workload must
    # reference the hashed name. If a reference is not rewritten, editing config
    # silently changes nothing.
    cms = [d["metadata"]["name"] for d in by_kind.get("ConfigMap", [])]
    hashed = [n for n in cms if n.startswith("tradexa-hub-config-")]
    check(len(hashed) == 1,
          f"{tag} expected one hash-suffixed ConfigMap, found {cms}")
    if hashed:
        for desc, spec in pod_specs(docs):
            for c in spec["containers"]:
                refs = [e["configMapRef"]["name"] for e in c.get("envFrom", [])
                        if "configMapRef" in e]
                if refs:
                    check(refs == hashed,
                          f"{tag} {desc}/{c['name']}: references {refs}, expected "
                          f"{hashed} — a stale reference means config edits never roll")

    # ── network posture ───────────────────────────────────────────────────
    nps = by_kind.get("NetworkPolicy", [])
    default_deny = [n for n in nps if n["spec"].get("podSelector") == {}
                    and set(n["spec"].get("policyTypes", [])) >= {"Ingress", "Egress"}]
    check(bool(default_deny),
          f"{tag} no default-deny NetworkPolicy — without one the allow rules are decoration")

    for np in nps:
        for eg in np["spec"].get("egress", []):
            for to in eg.get("to", []):
                block = to.get("ipBlock")
                if block and block.get("cidr") == "0.0.0.0/0":
                    excepts = set(block.get("except", []))
                    check("169.254.0.0/16" in excepts,
                          f"{tag} {np['metadata']['name']}: egress to 0.0.0.0/0 must "
                          "exclude 169.254.0.0/16 — that is the cloud metadata endpoint "
                          "that hands out node IAM credentials")

    # ── disruption budgets ────────────────────────────────────────────────
    pdb_names = {p["metadata"]["name"] for p in by_kind.get("PodDisruptionBudget", [])}
    for wl in by_kind.get("Deployment", []) + by_kind.get("StatefulSet", []):
        check(wl["metadata"]["name"] in pdb_names,
              f"{tag} {wl['metadata']['name']} has no PodDisruptionBudget — a node "
              "drain can take it out entirely")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlay", action="append",
                    help="overlay to validate (default: all)")
    args = ap.parse_args()

    overlays = args.overlay or sorted(
        p.name for p in OVERLAYS.iterdir() if (p / "kustomization.yaml").exists())

    for o in overlays:
        print(f"validating overlay: {o}")
        validate(o)

    print(f"\n{checks_run} checks run across {len(overlays)} overlay(s)")
    if failures:
        print(f"\n{len(failures)} FAILURE(S):\n", file=sys.stderr)
        for f in failures:
            print(f"  ✗ {f}", file=sys.stderr)
        return 1
    print("all invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
