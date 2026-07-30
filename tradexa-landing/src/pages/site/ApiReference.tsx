import { useState } from "react";
import { Link } from "react-router-dom";
import { DevShell, DevSection, Code, Callout, Method } from "@/components/site/dev/DevShell";
import { useRouteMeta } from "@/site/seo";
import { routeFor } from "@/site/routes";
import { cn } from "@/lib/utils";

type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

interface Endpoint {
  method: HttpMethod;
  path: string;
  summary: string;
  detail: string;
  sample: string;
}

const GROUPS: { name: string; endpoints: Endpoint[] }[] = [
  {
    name: "Strategies",
    endpoints: [
      {
        method: "GET",
        path: "/v1/strategies",
        summary: "List strategies and their current version",
        detail:
          "Returns every strategy on the account with its active version, mode (paper or live) and the regimes it is permitted to operate in. Performance is attributed per version, not per strategy, so the response carries the version id you will need for any metrics call.",
        sample: `{
  "data": [
    {
      "id": "stg_8f21",
      "name": "structure-v4",
      "version": 11,
      "mode": "live",
      "regimes": ["trend", "expanding"],
      "risk_per_trade": 0.005
    }
  ]
}`,
      },
      {
        method: "POST",
        path: "/v1/strategies/:id/promote",
        summary: "Promote paper to live, or demote",
        detail:
          "Changes the execution mode. Promotion is rejected if the strategy has no paper history, if the risk envelope would be breached on the first order, or if the connected venue is degraded. Demotion is always accepted and never closes open positions.",
        sample: `{ "mode": "live" }

→ 200 { "id": "stg_8f21", "mode": "live", "effective_at": "2026-07-30T09:14:02Z" }
→ 409 { "error": { "code": "no_paper_history", ... } }`,
      },
    ],
  },
  {
    name: "Decisions",
    endpoints: [
      {
        method: "GET",
        path: "/v1/decisions",
        summary: "Every evaluation, including the rejections",
        detail:
          "The rejections are the point. Filter by verdict to retrieve only what was declined and why — over a month this is a more useful record than the trades, because it is the only place you can see what the system nearly did.",
        sample: `GET /v1/decisions?verdict=veto&since=2026-07-01

{
  "data": [
    {
      "id": "dec_41c9",
      "symbol": "ARB/USDT",
      "conviction": 61,
      "verdict": "veto",
      "vetoed_by": "news_blackout",
      "rationale": "11 minutes to scheduled release; blackout window enforced.",
      "feature_vector_id": "fv_9a2e"
    }
  ]
}`,
      },
      {
        method: "GET",
        path: "/v1/decisions/:id/replay",
        summary: "Re-run a decision against its stored inputs",
        detail:
          "Deterministic. The stored feature vector is fed back through the current model ensemble, which is how you find out whether a change to weights would have altered a decision made months ago. Never places an order.",
        sample: `{
  "original": { "conviction": 61, "verdict": "veto" },
  "replayed": { "conviction": 68, "verdict": "veto" },
  "diverged": false
}`,
      },
    ],
  },
  {
    name: "Positions",
    endpoints: [
      {
        method: "GET",
        path: "/v1/positions",
        summary: "Open positions with live mark and R multiple",
        detail:
          "Includes the protective orders resident at the venue, so you can verify from outside the product that a stop actually exists rather than trusting that one was requested.",
        sample: `{
  "data": [
    {
      "symbol": "BTC/USDT", "side": "long", "size": "0.420",
      "entry": 68050.0, "mark": 68776.5, "r_multiple": 1.15,
      "protective": { "stop": 67420.0, "target": 69380.0, "resident": true }
    }
  ]
}`,
      },
      {
        method: "POST",
        path: "/v1/positions/:id/close",
        summary: "Close a position at market",
        detail:
          "A manual override. It is executed immediately and written to the audit log with the actor and source address, because an override that leaves no trace is indistinguishable from a bug.",
        sample: `{ "reason": "manual flatten before travel" }

→ 202 { "order_id": "ord_77b1", "status": "submitted" }`,
      },
    ],
  },
  {
    name: "Backtests",
    endpoints: [
      {
        method: "POST",
        path: "/v1/backtests",
        summary: "Queue a backtest or a parameter sweep",
        detail:
          "Runs against the same engine and risk service as live. Sweeps return the whole surface rather than the best cell — a peak surrounded by cliffs is an overfit and the response is shaped so it looks like one.",
        sample: `{
  "strategy": "structure-v4",
  "symbol": "BTC/USDT",
  "timeframe": "15m",
  "start": "2025-01-01",
  "end": "2026-01-01",
  "sweep": { "threshold": [68, 70, 72, 74, 76] }
}

→ 202 { "id": "bt_2f77", "status": "queued" }`,
      },
      {
        method: "GET",
        path: "/v1/backtests/:id",
        summary: "Fetch results, including the cost breakdown",
        detail:
          "Gross performance and cost drag are reported separately. A strategy whose edge disappears once fees, funding and modelled slippage are applied should be visibly that, not quietly netted.",
        sample: `{
  "status": "complete",
  "gross": { "expectancy": 0.44, "hit_rate": 0.46 },
  "costs": { "fees": -0.09, "funding": -0.02, "slippage": -0.02 },
  "net": { "expectancy": 0.31, "max_drawdown": -0.082 }
}`,
      },
    ],
  },
];

const ERRORS = [
  ["400", "invalid_request", "Malformed body or a parameter outside its allowed range."],
  ["401", "unauthenticated", "Missing, malformed or revoked API key."],
  ["403", "insufficient_scope", "The key is valid but not permitted for this operation."],
  ["409", "risk_veto", "The risk service refused the intent. `vetoed_by` names the rule."],
  ["422", "venue_rejected", "The exchange rejected the order; the venue's reason is passed through verbatim."],
  ["429", "rate_limited", "Retry after the seconds given in `Retry-After`."],
  ["503", "fail_closed", "A dependency is unreachable and trading has stopped by design."],
];

export default function ApiReferencePage() {
  const route = routeFor("/api")!;
  useRouteMeta(route);
  const [open, setOpen] = useState<string | null>("/v1/decisions");

  return (
    <DevShell
      eyebrow="API reference"
      title="One HTTP API, and no hidden verbs"
      intro="JSON over HTTPS, keyed authentication, cursor pagination and idempotent writes. Every endpoint the dashboard uses is an endpoint you can call — there is no private API the product reserves for itself."
    >
      <DevSection
        id="auth"
        title="Authentication"
        lead="A bearer token in the header. Keys are scoped, revocable, and never returned after creation."
      >
        <Code
          lang="bash"
          code={`curl https://api.trade-logx.com/v1/positions \\
  -H "Authorization: Bearer $NEXUS_API_KEY" \\
  -H "Nexus-Version: 2026-07-01"`}
        />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Callout title="Versioning">
            The <code className="font-mono text-white/70">Nexus-Version</code> header pins the
            response shape to a date. Omit it and you get the version your key was created
            against — never the newest, so a deploy on our side cannot change your parsing.
          </Callout>
          <Callout title="Rate limits">
            600 requests per minute per key, 20 per second burst. Limits are returned on every
            response in <code className="font-mono text-white/70">X-RateLimit-Remaining</code>;
            a 429 always carries <code className="font-mono text-white/70">Retry-After</code>.
          </Callout>
        </div>
      </DevSection>

      {GROUPS.map((group) => (
        <DevSection key={group.name} id={group.name.toLowerCase()} title={group.name}>
          <ul className="divide-y divide-white/[0.06] overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.015]">
            {group.endpoints.map((e) => {
              const isOpen = open === e.path;
              return (
                <li key={e.path}>
                  <button
                    onClick={() => setOpen(isOpen ? null : e.path)}
                    aria-expanded={isOpen}
                    className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-white/[0.03]"
                  >
                    <Method method={e.method} />
                    <code className="shrink-0 font-mono text-[13px] text-white/80">{e.path}</code>
                    <span className="ml-auto hidden truncate text-xs text-white/35 sm:block">
                      {e.summary}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 font-mono text-[13px] text-white/25 transition-transform duration-300",
                        isOpen && "rotate-45",
                      )}
                    >
                      +
                    </span>
                  </button>

                  <div
                    className="grid transition-[grid-template-rows] duration-400 ease-out motion-reduce:transition-none"
                    style={{ gridTemplateRows: isOpen ? "1fr" : "0fr" }}
                  >
                    <div className="overflow-hidden">
                      <div className="border-t border-white/[0.06] p-4">
                        <p className="mb-4 max-w-2xl text-sm leading-relaxed text-white/55">
                          {e.detail}
                        </p>
                        <Code lang="json" label="example" code={e.sample} />
                      </div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </DevSection>
      ))}

      <DevSection
        id="webhooks"
        title="Webhooks"
        lead="The same event envelope the internal bus uses, so a webhook payload and a replayed event are the same object."
      >
        <Code
          lang="json"
          label="envelope"
          code={`{
  "id": "evt_5c81",
  "type": "decision.vetoed",
  "occurred_at": "2026-07-30T09:18:00.412Z",
  "sequence": 4192837,
  "idempotency_key": "dec_41c9:veto",
  "data": { "...": "the decision object" }
}`}
        />
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-white/55">
          Delivery is at-least-once, so handlers must be idempotent — the{" "}
          <code className="font-mono text-white/70">idempotency_key</code> is stable across
          retries. Signatures are HMAC-SHA256 over the raw body; verify before parsing. Failed
          endpoints back off exponentially for 24 hours, and every attempt is visible in the
          dashboard rather than only in your logs.
        </p>
      </DevSection>

      <DevSection
        id="errors"
        title="Errors"
        lead="A stable code, a human sentence, and — where a rule caused it — the name of the rule."
      >
        <div className="overflow-x-auto rounded-xl border border-white/[0.08]">
          <table className="w-full min-w-[560px] border-collapse text-left">
            <thead>
              <tr className="border-b border-white/[0.08] bg-white/[0.02]">
                {["Status", "Code", "Means"].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-2.5 font-mono text-[10px] uppercase tracking-wider text-white/30"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ERRORS.map(([status, code, means]) => (
                <tr key={code} className="border-b border-white/[0.05] last:border-0">
                  <td className="px-4 py-2.5 font-mono text-[12px] text-white/70">{status}</td>
                  <td className="px-4 py-2.5 font-mono text-[12px] text-aqua-soft">{code}</td>
                  <td className="px-4 py-2.5 text-[13px] text-white/50">{means}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-4">
          <Callout tone="warn" title="503 is not an outage">
            <code className="font-mono text-white/70">fail_closed</code> means the risk service
            is unreachable and trading has stopped deliberately rather than continuing
            unchecked. Treat it as the system working. Current state is always on the{" "}
            <Link to="/status" className="text-gold-soft underline-offset-2 hover:underline">
              status page
            </Link>
            .
          </Callout>
        </div>
      </DevSection>
    </DevShell>
  );
}
