import { useState } from "react";
import { Check, Minus } from "lucide-react";
import { DevShell, DevSection, Code, Callout } from "@/components/site/dev/DevShell";
import { useRouteMeta } from "@/site/seo";
import { routeFor } from "@/site/routes";
import { cn } from "@/lib/utils";

interface Sdk {
  id: string;
  name: string;
  runtime: string;
  install: string;
  installLang: string;
  sample: string;
  sampleLang: string;
  status: "stable" | "beta";
}

const SDKS: Sdk[] = [
  {
    id: "python",
    name: "Python",
    runtime: "3.10+",
    install: "pip install tradelogx-nexus",
    installLang: "bash",
    sampleLang: "python",
    status: "stable",
    sample: `from nexus import Client

client = Client()  # reads NEXUS_API_KEY

for d in client.decisions.list(verdict="veto", limit=20):
    print(d.symbol, d.conviction, d.vetoed_by)
    print(" ", d.rationale)`,
  },
  {
    id: "typescript",
    name: "TypeScript",
    runtime: "Node 20+, Deno, Bun",
    install: "npm install @tradelogx/nexus",
    installLang: "bash",
    sampleLang: "typescript",
    status: "stable",
    sample: `import { Nexus } from "@tradelogx/nexus";

const nexus = new Nexus(); // reads NEXUS_API_KEY

for await (const d of nexus.decisions.list({ verdict: "veto" })) {
  console.log(d.symbol, d.conviction, d.vetoedBy);
  console.log(" ", d.rationale);
}`,
  },
  {
    id: "go",
    name: "Go",
    runtime: "1.22+",
    install: "go get github.com/tradelogx/nexus-go",
    installLang: "bash",
    sampleLang: "go",
    status: "stable",
    sample: `client := nexus.New() // reads NEXUS_API_KEY

it := client.Decisions.List(ctx, &nexus.DecisionQuery{
    Verdict: nexus.VerdictVeto,
})
for it.Next() {
    d := it.Value()
    fmt.Println(d.Symbol, d.Conviction, d.VetoedBy)
}
if err := it.Err(); err != nil {
    log.Fatal(err)
}`,
  },
  {
    id: "rust",
    name: "Rust",
    runtime: "1.78+, tokio",
    install: `cargo add tradelogx-nexus`,
    installLang: "bash",
    sampleLang: "rust",
    status: "beta",
    sample: `let client = nexus::Client::from_env()?;

let mut stream = client
    .decisions()
    .list(Query::new().verdict(Verdict::Veto));

while let Some(d) = stream.try_next().await? {
    println!("{} {} {:?}", d.symbol, d.conviction, d.vetoed_by);
}`,
  },
];

const PARITY: [string, boolean[]][] = [
  ["Typed models for every resource", [true, true, true, true]],
  ["Automatic cursor pagination", [true, true, true, true]],
  ["Retry with exponential backoff", [true, true, true, true]],
  ["Webhook signature verification", [true, true, true, false]],
  ["Streaming decision feed", [true, true, true, false]],
  ["Backtest helpers and dataframes", [true, false, false, false]],
];

export default function SdksPage() {
  const route = routeFor("/sdks")!;
  useRouteMeta(route);
  const [active, setActive] = useState(SDKS[0].id);
  const sdk = SDKS.find((s) => s.id === active)!;

  return (
    <DevShell
      eyebrow="SDKs"
      title="Four languages, one API, no second-class client"
      intro="Each client is generated from the same specification and then given an idiomatic surface by hand — iterators in Python, async generators in TypeScript, an errors-last iterator in Go. The parity table below is honest about where a runtime is still behind."
    >
      <DevSection id="install" title="Install and make a first call">
        {/* language switcher */}
        <div className="flex flex-wrap gap-1.5">
          {SDKS.map((s) => (
            <button
              key={s.id}
              onClick={() => setActive(s.id)}
              aria-pressed={s.id === active}
              className={cn(
                "group rounded-lg border px-3.5 py-2 text-left transition-all duration-200",
                s.id === active
                  ? "border-electric/45 bg-electric/[0.1]"
                  : "border-white/[0.08] hover:border-white/20 hover:bg-white/[0.03]",
              )}
            >
              <span className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-[13px] font-medium",
                    s.id === active ? "text-white" : "text-white/60",
                  )}
                >
                  {s.name}
                </span>
                {s.status === "beta" && (
                  <span className="rounded border border-gold/30 bg-gold/10 px-1.5 py-0.5 font-mono text-[9px] text-gold-soft">
                    beta
                  </span>
                )}
              </span>
              <span className="mt-0.5 block font-mono text-[10px] text-white/25">{s.runtime}</span>
            </button>
          ))}
        </div>

        <div className="mt-5 space-y-3">
          <Code lang={sdk.installLang} label="install" code={sdk.install} />
          <Code
            lang={sdk.sampleLang}
            label={`${sdk.name.toLowerCase()} · list vetoed decisions`}
            code={sdk.sample}
          />
        </div>

        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-white/45">
          Every client reads <code className="font-mono text-white/70">NEXUS_API_KEY</code> from
          the environment by default. None of them accept a key as a positional constructor
          argument, which is the single most common way a credential ends up committed.
        </p>
      </DevSection>

      <DevSection
        id="parity"
        title="Feature parity"
        lead="Where a client is behind, it says so here rather than in a changelog you would have to go looking for."
      >
        <div className="overflow-x-auto rounded-xl border border-white/[0.08]">
          <table className="w-full min-w-[560px] border-collapse text-left">
            <thead>
              <tr className="border-b border-white/[0.08] bg-white/[0.02]">
                <th className="px-4 py-2.5 font-mono text-[10px] uppercase tracking-wider text-white/30">
                  Capability
                </th>
                {SDKS.map((s) => (
                  <th
                    key={s.id}
                    className="px-3 py-2.5 text-center font-mono text-[10px] uppercase tracking-wider text-white/30"
                  >
                    {s.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PARITY.map(([capability, flags]) => (
                <tr key={capability} className="border-b border-white/[0.05] last:border-0">
                  <td className="px-4 py-2.5 text-[13px] text-white/60">{capability}</td>
                  {flags.map((ok, i) => (
                    <td key={i} className="px-3 py-2.5 text-center">
                      {ok ? (
                        <Check className="mx-auto h-3.5 w-3.5 text-emerald-soft" />
                      ) : (
                        <Minus className="mx-auto h-3.5 w-3.5 text-white/20" />
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DevSection>

      <DevSection id="versioning" title="Versioning and support">
        <div className="grid gap-3 sm:grid-cols-2">
          <Callout title="Semantic versioning">
            Majors are rare and always come with a migration guide and a deprecation period of at
            least six months. A minor never changes an existing signature.
          </Callout>
          <Callout title="Pinned response shapes">
            Clients send the <code className="font-mono text-white/70">Nexus-Version</code> header
            they were built against, so upgrading the platform cannot change what your code
            parses. Upgrading the client is the deliberate act.
          </Callout>
        </div>

        <p className="mt-5 max-w-2xl text-sm leading-relaxed text-white/45">
          All four clients are published under the same permissive licence as the rest of what we
          open source, and the generator that produces them is public too — the details are on
          the open-source page.
        </p>
      </DevSection>
    </DevShell>
  );
}
