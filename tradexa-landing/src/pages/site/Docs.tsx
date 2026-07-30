import { Link } from "react-router-dom";
import { ArrowRight, BookOpen, Compass, GitBranch, Layers, ShieldCheck } from "lucide-react";
import { DevShell, DevSection, Code, Callout } from "@/components/site/dev/DevShell";
import { useRouteMeta } from "@/site/seo";
import { routeFor, prefetchRoute } from "@/site/routes";

const GUIDES = [
  {
    icon: Compass,
    title: "Connect an exchange",
    body: "Create a trade-only key, allowlist our egress addresses, and attach it. Keys carrying withdrawal permission are refused at connection time.",
    time: "5 min",
  },
  {
    icon: Layers,
    title: "Run your first backtest",
    body: "Point a strategy at a symbol and a date range. The Lab runs the same engine and risk path as live, so the result is a rehearsal rather than a different program.",
    time: "10 min",
  },
  {
    icon: ShieldCheck,
    title: "Set a risk envelope",
    body: "Daily and weekly loss budgets, exposure ceiling, correlation limits and per-strategy regime allowlists. Nothing trades outside them.",
    time: "8 min",
  },
  {
    icon: GitBranch,
    title: "Promote paper to live",
    body: "Paper mode consumes the live feed and produces identical journal output. Promotion is a flag, not a rewrite — and it is reversible.",
    time: "3 min",
  },
];

const CONCEPTS = [
  ["Conviction score", "A weighted 0–100 across nine qualifications. The score is the output; the breakdown is always visible alongside it."],
  ["Regime", "Volatility state and directional persistence, classified on three horizons. Strategies declare which regimes they may operate in."],
  ["Feature vector", "The fixed-shape input the models score, stored verbatim so a decision is replayable months later with the exact inputs it saw."],
  ["Risk envelope", "The thirteen checks an order intent must clear. A separate service with veto power; it fails closed."],
  ["Analogue recall", "Previous trades in similar conditions, consulted at decision time. How the system stops repeating a mistake it has paid for."],
  ["Order intent", "A sized decision that has not yet been through risk. Intents become orders only after the envelope clears."],
];

export default function DocsPage() {
  const route = routeFor("/docs")!;
  useRouteMeta(route);

  return (
    <DevShell
      eyebrow="Documentation"
      title={
        <>
          Everything you need to run it,
          <br className="hidden sm:block" /> in the order you need it
        </>
      }
      intro="Start with the quickstart, which gets a strategy backtesting in about ten minutes. The concepts section explains the vocabulary the rest of the platform uses, and the guides cover the things people actually get stuck on."
    >
      <DevSection
        id="quickstart"
        title="Quickstart"
        lead="Install the client, authenticate, and run a backtest. This does not touch an exchange and cannot place an order."
      >
        <div className="space-y-3">
          <Code lang="bash" label="1 · install" code={`pip install tradelogx-nexus`} />
          <Code
            lang="bash"
            label="2 · authenticate"
            code={`export NEXUS_API_KEY="nxs_live_..."   # from Settings → API keys`}
          />
          <Code
            lang="python"
            label="3 · backtest"
            code={`from nexus import Client

client = Client()               # reads NEXUS_API_KEY

result = client.backtest(
    strategy="structure-v4",
    symbol="BTC/USDT",
    timeframe="15m",
    start="2025-01-01",
    end="2026-01-01",
    risk_per_trade=0.005,       # 0.5% of equity
)

print(result.expectancy)        # 0.31R
print(result.max_drawdown)      # -0.082
print(result.trades[0].rationale)`}
          />
        </div>

        <div className="mt-5">
          <Callout tone="warn" title="Before you go live">
            A backtest that looks good is a hypothesis, not a result. Run the same strategy in
            paper mode against the live feed for a full month before committing capital — it
            costs nothing and produces an identical journal. The{" "}
            <Link to="/risk-disclosure" className="text-gold-soft underline-offset-2 hover:underline">
              risk disclosure
            </Link>{" "}
            covers why this matters more than it sounds.
          </Callout>
        </div>
      </DevSection>

      <DevSection
        id="guides"
        title="Guides"
        lead="Task-shaped, not feature-shaped. Each one ends with something working."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          {GUIDES.map((g) => (
            <article
              key={g.title}
              className="group rounded-xl border border-white/[0.08] bg-white/[0.02] p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-electric/30 hover:bg-white/[0.04]"
            >
              <div className="flex items-start justify-between gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-electric/25 bg-electric/[0.08] text-electric-soft transition-transform duration-300 group-hover:scale-110">
                  <g.icon className="h-4 w-4" />
                </span>
                <span className="font-mono text-[10px] text-white/25">{g.time}</span>
              </div>
              <h3 className="mt-4 text-[15px] font-semibold text-white">{g.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/50">{g.body}</p>
            </article>
          ))}
        </div>
      </DevSection>

      <DevSection
        id="concepts"
        title="Concepts"
        lead="The vocabulary the API, the dashboard and the journal all assume. Worth ten minutes before the reference."
      >
        <dl className="divide-y divide-white/[0.06] rounded-xl border border-white/[0.08] bg-white/[0.015]">
          {CONCEPTS.map(([term, def]) => (
            <div key={term} className="grid gap-1 p-4 sm:grid-cols-[190px_1fr] sm:gap-5">
              <dt className="font-mono text-[13px] text-aqua-soft">{term}</dt>
              <dd className="text-sm leading-relaxed text-white/55">{def}</dd>
            </div>
          ))}
        </dl>
      </DevSection>

      <DevSection
        id="next"
        title="Where to go next"
        lead="The reference is exhaustive; these three pages are the ones people need first."
      >
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            ["/api", "API reference", "Every endpoint, with request and response shapes"],
            ["/sdks", "SDKs", "Python, TypeScript, Go and Rust clients"],
            ["/how-it-works", "How it works", "The seven stages a trade passes through"],
          ].map(([path, label, blurb]) => (
            <Link
              key={path}
              to={path}
              onPointerEnter={() => prefetchRoute(path)}
              className="group flex flex-col rounded-xl border border-white/[0.08] bg-white/[0.02] p-4 transition-all duration-300 hover:-translate-y-0.5 hover:border-electric/30"
            >
              <span className="flex items-center gap-1.5 text-[14px] font-medium text-white">
                {label}
                <ArrowRight className="h-3.5 w-3.5 text-electric-soft opacity-0 transition-all duration-300 group-hover:translate-x-0.5 group-hover:opacity-100" />
              </span>
              <span className="mt-1 text-xs leading-relaxed text-white/45">{blurb}</span>
            </Link>
          ))}
        </div>

        <p className="mt-6 flex items-start gap-2 text-sm leading-relaxed text-white/40">
          <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-white/25" />
          Something missing or wrong here is a documentation bug and worth reporting the same way
          as any other — through the{" "}
          <Link to="/support" className="text-electric-soft underline-offset-2 hover:underline">
            support center
          </Link>
          .
        </p>
      </DevSection>
    </DevShell>
  );
}
