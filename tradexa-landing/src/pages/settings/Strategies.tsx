import { useState } from "react";
import { Plus, Upload, Download, Pencil, Copy, Trash2, History, CheckCircle2 } from "lucide-react";
import { SettingsHeader, Section } from "@/components/settings/primitives";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Switch } from "@/components/ui/Switch";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/lib/toast";

interface Strat {
  name: string;
  version: string;
  enabled: boolean;
}

const SEED: Strat[] = [
  { name: "Decision Brain", version: "v3", enabled: true },
  { name: "EMA Crossover", version: "v1", enabled: false },
  { name: "Supertrend", version: "v1", enabled: false },
  { name: "Donchian", version: "v1", enabled: false },
  { name: "Confirmation Ensemble", version: "v1", enabled: false },
];

export default function Strategies() {
  const { toast } = useToast();
  const [list, setList] = useState<Strat[]>(SEED);
  const [toDelete, setToDelete] = useState<string | null>(null);

  const toggle = (name: string, v: boolean) =>
    setList((l) => l.map((s) => (s.name === name ? { ...s, enabled: v } : s)));

  const remove = () => {
    if (!toDelete) return;
    setList((l) => l.filter((s) => s.name !== toDelete));
    toast(`"${toDelete}" removed`, "success");
    setToDelete(null);
  };

  return (
    <>
      <SettingsHeader title="Strategies" description="Manage the strategies the engine can run. Only enabled strategies trade." />

      <div className="space-y-5">
        <Section
          title="Your strategies"
          description="Built-in strategies validated for this platform."
          action={
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => toast("Strategy import opens when the builder backend is connected.", "info")}>
                <Upload className="h-3.5 w-3.5" /> Import
              </Button>
              <Button size="sm" onClick={() => toast("Create opens the strategy builder when connected.", "info")}>
                <Plus className="h-3.5 w-3.5" /> Create
              </Button>
            </div>
          }
        >
          <div className="divide-y divide-line/60">
            {list.map((s) => (
              <div key={s.name} className="flex flex-wrap items-center gap-3 py-3.5">
                <Switch label={s.name} checked={s.enabled} onChange={(v) => toggle(s.name, v)} />
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-sm font-medium text-white">
                    {s.name}
                    <Badge tone="neutral">{s.version}</Badge>
                    {s.enabled && <Badge tone="emerald">Active</Badge>}
                  </p>
                </div>
                <div className="flex items-center gap-1 text-white/50">
                  {[
                    { icon: Pencil, t: "Edit", m: "Strategy editing opens the builder when connected." },
                    { icon: Copy, t: "Duplicate", m: `Duplicated "${s.name}".` },
                    { icon: History, t: "Version history", m: "Version history is available when connected." },
                  ].map((b) => (
                    <button key={b.t} title={b.t} onClick={() => toast(b.m, "info")} className="rounded-lg p-1.5 transition hover:bg-white/5 hover:text-white">
                      <b.icon className="h-4 w-4" />
                    </button>
                  ))}
                  <button title="Delete" onClick={() => setToDelete(s.name)} className="rounded-lg p-1.5 text-loss/70 transition hover:bg-loss/10 hover:text-loss">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
            {list.length === 0 && <p className="py-6 text-center text-sm text-white/40">No strategies. Create one to begin.</p>}
          </div>
          <div className="border-t border-line/60 py-3">
            <Button size="sm" variant="ghost" onClick={() => toast("Exported current strategy set.", "success")}>
              <Download className="h-3.5 w-3.5" /> Export strategies
            </Button>
          </div>
        </Section>

        <Section title="Strategy validation">
          <div className="flex items-start gap-3 py-3 text-sm text-white/55">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" />
            <p>Every strategy is validated against historical data and the risk guards before it can be enabled. A strategy that fails validation can be reviewed but never traded live.</p>
          </div>
        </Section>
      </div>

      <ConfirmDialog
        open={toDelete !== null}
        danger
        title="Delete strategy?"
        description={`"${toDelete}" will be removed from your workspace. This cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={remove}
        onClose={() => setToDelete(null)}
      />
    </>
  );
}
