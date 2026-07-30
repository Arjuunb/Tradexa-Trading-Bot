import { Link } from "react-router-dom";
import { ArrowUpRight, Bug, GitBranch, Tag } from "lucide-react";
import { DevShell, DevSection, Code, Callout } from "@/components/site/dev/DevShell";
import { useRouteMeta } from "@/site/seo";
import { routeFor, prefetchRoute } from "@/site/routes";
import { REPO_URL } from "@/site/platform";

interface Repo {
  name: string;
  what: string;
  language: string;
  branch: string;
}

const REPOS: Repo[] = [
  {
    name: "tradexa-trading-bot",
    what: "The engine, the risk service and the platform. The repository this site is built from.",
    language: "Python · TypeScript",
    branch: "main",
  },
  {
    name: "risk-engine-spec",
    what: "Thirteen responsibilities as an executable specification, with a conformance suite.",
    language: "Python",
    branch: "main",
  },
  {
    name: "event-envelope",
    what: "Envelope format, type registry and replay semantics. Also the webhook payload schema.",
    language: "Python · JSON Schema",
    branch: "main",
  },
  {
    name: "nexus-clients",
    what: "Python, TypeScript, Go and Rust SDKs, and the generator that produces them.",
    language: "Multi",
    branch: "main",
  },
];

export default function GitHubPage() {
  const route = routeFor("/github")!;
  useRouteMeta(route);

  return (
    <DevShell
      eyebrow="GitHub"
      title="Where the code lives, and how to move it"
      intro="Four repositories, one release process, and a strong preference for small changes that arrive with a failing test. This page is the map; the repositories themselves are the territory."
    >
      <DevSection id="repos" title="Repositories">
        <ul className="space-y-2.5">
          {REPOS.map((r) => (
            <li key={r.name}>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="group flex flex-wrap items-start gap-x-4 gap-y-2 rounded-xl border border-white/[0.08] bg-white/[0.02] p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-electric/30 hover:bg-white/[0.04]"
              >
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <code className="font-mono text-[14px] text-white">{r.name}</code>
                    <ArrowUpRight className="h-3.5 w-3.5 text-electric-soft opacity-0 transition-all duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:opacity-100" />
                  </span>
                  <span className="mt-2 block text-sm leading-relaxed text-white/50">{r.what}</span>
                </span>
                <span className="flex shrink-0 gap-4 font-mono text-[10px] text-white/30">
                  <span className="inline-flex items-center gap-1.5">
                    <GitBranch className="h-3 w-3" />
                    {r.branch}
                  </span>
                  <span>{r.language}</span>
                </span>
              </a>
            </li>
          ))}
        </ul>
      </DevSection>

      <DevSection
        id="issues"
        title="Filing an issue that gets fixed"
        lead="Maintainer time goes to issues that can be reproduced. Everything below exists to make that possible in one round trip rather than four."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Callout title="What to include">
            The version, the exact call or configuration, what you expected, what happened, and
            a decision or backtest id if one is involved — that id is enough for us to replay the
            exact inputs the engine saw.
          </Callout>
          <Callout tone="warn" title="What to leave out">
            API keys, exchange credentials, account identifiers and full log dumps. Redact before
            pasting. A public issue is public immediately and permanently.
          </Callout>
        </div>

        <div className="mt-4">
          <Code
            lang="markdown"
            label="a good issue"
            code={`### What happened
\`POST /v1/backtests\` with a sweep over \`threshold\` returns 202,
then the job sits in \`queued\` indefinitely.

### Expected
The job transitions to \`running\` within a few seconds, as a
single-parameter backtest does.

### Reproduce
- client: tradelogx-nexus 2.4.1, Python 3.12
- backtest id: bt_2f77
- sweep: { "threshold": [68, 70, 72, 74, 76] }
- single-parameter runs on the same strategy work

### Notes
Started after upgrading from 2.3.x. Reverting the client does
not help, so it looks server-side.`}
          />
        </div>

        <div className="mt-5 flex items-start gap-2.5 rounded-xl border border-loss/25 bg-loss/[0.05] p-4">
          <Bug className="mt-0.5 h-4 w-4 shrink-0 text-loss-soft" />
          <p className="text-sm leading-relaxed text-white/60">
            <span className="font-medium text-white">Security issues never go in a public
            issue.</span>{" "}
            A vulnerability in a trading system with connected exchange keys is not something to
            disclose in a tracker while it is unpatched. The private disclosure route is on the{" "}
            <Link to="/security" className="text-loss-soft underline-offset-2 hover:underline">
              security page
            </Link>
            .
          </p>
        </div>
      </DevSection>

      <DevSection
        id="pull-requests"
        title="Pull requests"
        lead="One change per pull request. A branch that fixes a bug and also renames three files is two reviews wearing one hat."
      >
        <ol className="space-y-2.5">
          {[
            "Open an issue first for anything larger than a fix — agreeing on the approach costs a comment and saves a rewrite.",
            "Add a test that fails before the change and passes after. For risk semantics this is not optional; the conformance suite is the specification.",
            "Keep the diff readable. Formatting changes belong in their own commit, and preferably their own pull request.",
            "Sign off your commits (`git commit -s`). There is no CLA; a DCO sign-off is enough.",
            "Expect review from two maintainers on risk semantics and one elsewhere. Reviews are public, and disagreement in them is normal rather than a problem.",
          ].map((step, i) => (
            <li key={step} className="flex gap-3.5">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-electric/25 bg-electric/[0.08] font-mono text-[11px] text-electric-soft">
                {i + 1}
              </span>
              <span className="text-sm leading-relaxed text-white/55">{step}</span>
            </li>
          ))}
        </ol>
      </DevSection>

      <DevSection id="releases" title="Releases">
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.015] p-5">
          <div className="flex items-center gap-2">
            <Tag className="h-4 w-4 text-aqua-soft" />
            <h3 className="text-[14px] font-semibold text-white">How a version is cut</h3>
          </div>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-white/55">
            Releases are tagged from <code className="font-mono text-white/70">main</code>, and
            the changelog is derived from commits rather than written afterwards — which is why
            commit messages are reviewed as part of the diff. Packages publish to PyPI, npm,
            pkg.go.dev and crates.io from the tag, never from a developer machine.
          </p>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-white/45">
            Platform deploys are separate and continuous. A client release never requires a
            platform upgrade: response shapes are pinned by the{" "}
            <code className="font-mono text-white/70">Nexus-Version</code> header, described on
            the{" "}
            <Link
              to="/api"
              onPointerEnter={() => prefetchRoute("/api")}
              className="text-electric-soft underline-offset-2 hover:underline"
            >
              API reference
            </Link>
            .
          </p>
        </div>

        <a
          href={REPO_URL}
          target="_blank"
          rel="noreferrer"
          className="group mt-5 inline-flex items-center gap-2 rounded-xl border border-electric/35 bg-electric/[0.08] px-4 py-2.5 text-sm text-electric-soft transition-all duration-200 hover:border-electric/60 hover:bg-electric/[0.14]"
        >
          Open the repository on GitHub
          <ArrowUpRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
        </a>
      </DevSection>
    </DevShell>
  );
}
