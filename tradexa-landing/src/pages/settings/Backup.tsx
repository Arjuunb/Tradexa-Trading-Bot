import { useRef } from "react";
import { Download, Upload, Save, DatabaseBackup } from "lucide-react";
import { SettingsHeader, Section, SettingRow, NotConnected } from "@/components/settings/primitives";
import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import { useSettings } from "@/settings/store";
import { settingsSchema, type SettingsSection } from "@/settings/schema";
import { useToast } from "@/lib/toast";

const KEY = "tradexa.settings.v1";

export default function Backup() {
  const { settings, setSection, update } = useSettings();
  const { toast } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);

  const download = () => {
    const blob = new Blob([JSON.stringify(settings, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "tradelogx-nexus-settings.json";
    a.click();
    URL.revokeObjectURL(url);
    toast("Configuration downloaded", "success");
  };

  const onImport = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = settingsSchema.deepPartial().parse(JSON.parse(String(reader.result)));
        (Object.keys(parsed) as SettingsSection[]).forEach((k) => {
          const merged = { ...settings[k], ...(parsed[k] as object) } as never;
          setSection(k, merged);
        });
        toast("Settings imported", "success");
      } catch {
        toast("Could not import — invalid settings file", "error");
      }
    };
    reader.readAsText(file);
  };

  const manualBackup = () => {
    try {
      localStorage.setItem(`${KEY}.backup`, JSON.stringify(settings));
      toast("Manual backup saved locally", "success");
    } catch {
      toast("Backup failed — storage unavailable", "error");
    }
  };

  return (
    <>
      <SettingsHeader title="Backup & Restore" description="Export, import and back up your TradeLogX Nexus configuration." />

      <div className="space-y-5">
        <Section title="Configuration">
          <SettingRow label="Export settings" description="Download your full configuration as a JSON file.">
            <Button variant="secondary" onClick={download}><Download className="h-4 w-4" /> Export</Button>
          </SettingRow>
          <SettingRow label="Import settings" description="Restore configuration from a previously exported file.">
            <Button variant="secondary" onClick={() => fileRef.current?.click()}><Upload className="h-4 w-4" /> Import</Button>
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onImport(f);
                e.target.value = "";
              }}
            />
          </SettingRow>
          <SettingRow label="Manual backup" description="Save a local snapshot you can restore from this browser.">
            <Button variant="secondary" onClick={manualBackup}><Save className="h-4 w-4" /> Back up now</Button>
          </SettingRow>
        </Section>

        <Section title="Automatic backups">
          <SettingRow label="Enable automatic backups" description="Periodically snapshot your configuration.">
            <Switch label="Automatic backups" checked={settings.automation.autoBackups} onChange={(v) => update("automation", { autoBackups: v })} />
          </SettingRow>
        </Section>

        <Section title="Restore points">
          <div className="py-3">
            <NotConnected icon={DatabaseBackup} detail="Server-side restore points (versioned snapshots you can roll back to) appear here once connected to the TradeLogX Nexus backend." />
          </div>
        </Section>
      </div>
    </>
  );
}
