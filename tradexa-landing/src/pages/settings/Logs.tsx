import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, LogIn, RefreshCw, ScrollText, Search } from "lucide-react";
import { SettingsHeader, Section, NotConnected } from "@/components/settings/primitives";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { hubConfig, hubFetch } from "@/lib/hub";
import { cn } from "@/lib/utils";

/** One entry from the engine's real ledger log (GET /ledger/logs). */
interface LogLine {
  ts: string;
  level: string;
  stage: string;
  symbol?: string | null;
  message: string;
}

// Filters map to the ledger's REAL stages/levels — no invented categories.
const CATEGORIES: { value: string; label: string }[] = [
  { value: "all", label: "All logs" },
  { value: "stage:execution", label: "Trading (execution)" },
  { value: "stage:risk", label: "Risk" },
  { value: "stage:audit", label: "Audit" },
  { value: "stage:ops", label: "Ops / system" },
  { value: "stage:research", label: "AI / research" },
  { value: "stage:controls", label: "Controls" },
  { value: "level:error", label: "Errors" },
  { value: "level:warning", label: "Warnings" },
];

const levelTone = (l: string) => (l === "error" ? "loss" : l === "warning" ? "gold" : "neutral") as
  | "loss"
  | "gold"
  | "neutral";

export default function Logs() {
  const signedIn = hubConfig() !== null;
  const [query, setQuery] = useState<string>("");
  const [category, setCategory] = useState<string>("all");
  const [logs, setLogs] = useState<LogLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!hubConfig()) return;
    hubFetch<LogLine[]>("/ledger/logs?limit=300")
      .then((d) => {
        setLogs(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
    if (!signedIn) return;
    const iv = window.setInterval(load, 6000);
    return () => window.clearInterval(iv);
  }, [load, signedIn]);

  const rows = useMemo(() => {
    let out = logs ?? [];
    if (category.startsWith("stage:")) out = out.filter((l) => l.stage === category.slice(6));
    if (category.startsWith("level:")) out = out.filter((l) => l.level === category.slice(6));
    const q = query.trim().toLowerCase();
    if (q)
      out = out.filter(
        (l) => l.message.toLowerCase().includes(q) || (l.symbol ?? "").toLowerCase().includes(q),
      );
    return out;
  }, [logs, category, query]);

  return (
    <>
      <SettingsHeader
        title="Logs"
        description="The engine's real runtime log stream — every decision, rejection and system event."
      />

      <Section
        title="Log viewer"
        description={signedIn ? "Live from the engine ledger · refreshes every 6s." : "Live logs are served by the Tradexa backend."}
        action={
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={load} disabled={!signedIn}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!signedIn}
              onClick={() => window.open("/ledger/logs/export?fmt=csv", "_blank")}
            >
              <Download className="h-3.5 w-3.5" /> Export CSV
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center">
          <div className="flex-1">
            <Input
              icon={<Search className="h-4 w-4" />}
              placeholder="Search message or symbol…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search logs"
            />
          </div>
          <div className="sm:w-56">
            <Select
              options={CATEGORIES}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              aria-label="Log category"
            />
          </div>
        </div>

        <div className="pb-3">
          {!signedIn ? (
            <NotConnected
              icon={LogIn}
              title="Sign in to view live logs"
              detail="The engine's log stream is operator-only. Sign in and reload — the viewer activates automatically."
            />
          ) : error ? (
            <NotConnected icon={ScrollText} title="Engine unreachable" detail={`Could not load logs (${error}). Refresh to retry.`} />
          ) : logs === null ? (
            <p className="py-8 text-center text-sm text-white/40">Loading logs…</p>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-sm text-white/40">
              No log lines match{query || category !== "all" ? " your filters" : " yet — the engine logs as it works"}.
            </p>
          ) : (
            <div className="max-h-[32rem] overflow-y-auto rounded-xl border border-line bg-ink-800/50">
              {rows.map((l, i) => (
                <div
                  key={`${l.ts}-${i}`}
                  className={cn(
                    "flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-line/50 px-3.5 py-2 font-mono text-[12px] last:border-0",
                    l.level === "error" && "bg-loss/[0.04]",
                  )}
                >
                  <span className="shrink-0 text-white/30">{l.ts?.slice(0, 19).replace("T", " ")}</span>
                  <Badge tone={levelTone(l.level)}>{l.level}</Badge>
                  <span className="shrink-0 uppercase tracking-wider text-gold-soft/70">{l.stage}</span>
                  {l.symbol && <span className="shrink-0 text-white/50">{l.symbol}</span>}
                  <span className="min-w-0 flex-1 text-white/75">{l.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Section>
    </>
  );
}
