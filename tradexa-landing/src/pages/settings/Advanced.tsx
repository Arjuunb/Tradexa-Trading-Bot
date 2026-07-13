import { Lock } from "lucide-react";
import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Switch } from "@/components/ui/Switch";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { useSettings } from "@/settings/store";
import type { Settings } from "@/settings/schema";
import { useToast } from "@/lib/toast";

const FLAGS: { key: keyof Settings["advanced"]; label: string; desc: string }[] = [
  { key: "developerMode", label: "Developer mode", desc: "Show raw payloads, IDs and developer tooling." },
  { key: "debugMode", label: "Debug mode", desc: "Verbose logging for troubleshooting." },
  { key: "experimentalFeatures", label: "Experimental features", desc: "Opt into unreleased, unstable features." },
  { key: "performanceMode", label: "Performance mode", desc: "Reduce visual effects for lower resource use." },
  { key: "sandboxMode", label: "Sandbox mode", desc: "Isolate changes without touching live config." },
];

export default function Advanced() {
  const { settings, update } = useSettings();
  const { toast } = useToast();
  const a = settings.advanced;

  return (
    <>
      <SettingsHeader title="Advanced" description="Power-user options and platform diagnostics." />

      <div className="space-y-5">
        <Section title="Feature flags">
          {FLAGS.map((f) => (
            <SettingRow key={f.key} label={f.label} description={f.desc}>
              <Switch label={f.label} checked={a[f.key] as boolean} onChange={(v) => update("advanced", { [f.key]: v } as Partial<Settings["advanced"]>)} />
            </SettingRow>
          ))}
        </Section>

        <Section title="Trading mode" description="Live execution is hard-locked platform-wide.">
          <SettingRow label="Paper trading" description="The engine simulates fills on real market data.">
            <div className="flex items-center gap-2 sm:justify-end">
              <Badge tone="emerald">Enabled</Badge>
              <Switch label="Paper trading" checked disabled onChange={() => {}} />
            </div>
          </SettingRow>
          <SettingRow
            label="Live trading"
            description={
              <span className="inline-flex items-center gap-1.5">
                <Lock className="h-3.5 w-3.5 text-gold" />
                Hard-locked by design. Real-money execution is never enabled from the UI.
              </span>
            }
          >
            <div className="flex items-center gap-2 sm:justify-end">
              <Badge tone="neutral">Locked</Badge>
              <Switch label="Live trading" checked={false} disabled onChange={() => {}} />
            </div>
          </SettingRow>
        </Section>

        <Section title="Diagnostics">
          <SettingRow label="API diagnostics" description="Run a connectivity and health check.">
            <Button variant="secondary" onClick={() => toast("Diagnostics run against your backend when VITE_API_BASE is configured.", "info")}>
              Run diagnostics
            </Button>
          </SettingRow>
        </Section>
      </div>
    </>
  );
}
