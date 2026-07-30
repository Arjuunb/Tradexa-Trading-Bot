import { Link } from "react-router-dom";
import { Scale, Package, GitPullRequest } from "lucide-react";
import { DevShell, DevSection, Code, Callout } from "@/components/site/dev/DevShell";
import { useRouteMeta } from "@/site/seo";
import { routeFor, prefetchRoute } from "@/site/routes";

interface Project {
  name: string;
  licence: string;
  summary: string;
  why: string;
}

const PROJECTS: Project[] = [
  {
    name: "risk-engine-spec",
    licence: "Apache-2.0",
    summary: "The thirteen responsibilities, written as an executable specification.",
    why: "A risk system you cannot inspect is a risk system you are taking on faith. The spec and its conformance suite are public so the behaviour can be checked rather than believed — including by people who never use the platform.",
  },
  {
    name: "event-envelope",
    licence: "Apache-2.0",
    summary: "The envelope format, registry and replay semantics used on the internal bus.",
    why: "It is also the webhook payload format. Publishing it means an integrator can generate types and test against a real schema instead of reverse-engineering examples.",
  },
  {
    name: "backtest-harness",
    licence: "Apache-2.0",
    summary: "Cost modelling, walk-forward windowing and the parameter-surface reporter.",
    why: "Backtest results are only meaningful if you can see how costs were modelled. This is the part where the numbers are made, so it is the part most worth being open.",
  },
  {
    name: "nexus-clients",
    licence: "MIT",
    summary: "The Python, TypeScript, Go and Rust SDKs, plus the generator that produces them.",
    why: "Client libraries live in your codebase, so they should be readable, forkable and patchable without waiting for us.",
  },
];

export default function OpenSourcePage() {
  const route = routeFor("/open-source")!;
  useRouteMeta(route);

  return (
    <DevShell
      eyebrow="Open source"
      title="The parts worth checking are the parts we publish"
      intro="Not everything is open, and the split is not arbitrary. The components that make claims you would otherwise have to take on trust — how risk is enforced, how costs are modelled, what an event actually contains — are public. The models and the hosted platform are not."
    >
      <DevSection
        id="projects"
        title="What is public"
        lead="Four repositories, two licences, and a reason for each."
      >
        <ul className="space-y-3">
          {PROJECTS.map((p) => (
            <li
              key={p.name}
              className="group rounded-xl border border-white/[0.08] bg-white/[0.02] p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-electric/30"
            >
              <div className="flex flex-wrap items-center gap-3">
                <Package className="h-4 w-4 shrink-0 text-electric-soft" />
                <code className="font-mono text-[14px] text-white">{p.name}</code>
                <span className="rounded border border-white/[0.1] px-2 py-0.5 font-mono text-[10px] text-white/45">
                  {p.licence}
                </span>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-white/60">{p.summary}</p>
              <p className="mt-2 text-sm leading-relaxed text-white/40">{p.why}</p>
            </li>
          ))}
        </ul>
      </DevSection>

      <DevSection id="not-open" title="What is not, and why">
        <div className="grid gap-3 sm:grid-cols-2">
          <Callout tone="warn" title="The model ensemble">
            The structure, momentum and analogue-recall models and their calibration are closed.
            They are the product. Their <em>inputs</em> and <em>outputs</em> are fully inspectable
            per decision, which is the property that actually matters to someone deciding whether
            to trust a verdict.
          </Callout>
          <Callout tone="warn" title="The hosted platform">
            Deployment, tenancy and key custody are closed for the ordinary reason: publishing the
            exact shape of the system that holds trading credentials makes it easier to attack and
            no easier to verify.
          </Callout>
        </div>

        <p className="mt-5 max-w-2xl text-sm leading-relaxed text-white/45">
          We would rather state this boundary plainly than describe the project as "open source"
          and let the ambiguity do work. What is open is genuinely open — Apache-2.0 and MIT, no
          commons clause, no source-available licence pretending otherwise.
        </p>
      </DevSection>

      <DevSection
        id="contributing"
        title="Contributing"
        lead="Small and specific beats large and speculative. A failing test that reproduces a bug is the most useful thing you can send."
      >
        <Code
          lang="bash"
          label="get set up"
          code={`git clone https://github.com/tradelogx/risk-engine-spec
cd risk-engine-spec
make install          # dev dependencies and hooks
make test             # the conformance suite, ~40s
make test-watch       # while you work`}
        />

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          {[
            [Scale, "Licence", "Contributions are under the repository's licence. No CLA — a DCO sign-off on each commit is enough."],
            [GitPullRequest, "Review", "Two maintainers on anything touching risk semantics, one on everything else. Reviews are public."],
            [Package, "Releases", "Tagged from main, changelog derived from commits, published to PyPI, npm, pkg.go.dev and crates.io."],
          ].map(([Icon, title, body]) => {
            const I = Icon as typeof Scale;
            return (
              <div key={title as string} className="rounded-xl border border-white/[0.08] bg-white/[0.015] p-4">
                <I className="h-4 w-4 text-aqua-soft" />
                <h3 className="mt-3 text-[13px] font-semibold text-white">{title as string}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-white/45">{body as string}</p>
              </div>
            );
          })}
        </div>

        <p className="mt-6 max-w-2xl text-sm leading-relaxed text-white/45">
          Where the repositories live and what a good issue looks like is covered on the{" "}
          <Link
            to="/github"
            onPointerEnter={() => prefetchRoute("/github")}
            className="text-electric-soft underline-offset-2 hover:underline"
          >
            GitHub page
          </Link>
          . Security issues are the exception to all of this — never open a public issue for one;
          the disclosure route is on the{" "}
          <Link to="/security" className="text-electric-soft underline-offset-2 hover:underline">
            security page
          </Link>
          .
        </p>
      </DevSection>
    </DevShell>
  );
}
