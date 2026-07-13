import { useState } from "react";
import { Download } from "lucide-react";
import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Switch } from "@/components/ui/Switch";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useSettings } from "@/settings/store";
import type { Settings } from "@/settings/schema";
import { useToast } from "@/lib/toast";

export default function Privacy() {
  const { settings, update } = useSettings();
  const { toast } = useToast();
  const p = settings.privacy;
  const set = (patch: Partial<Settings["privacy"]>) => update("privacy", patch);
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <>
      <SettingsHeader title="Data & Privacy" description="Control your data and how Tradexa uses it. Autosaves." />

      <div className="space-y-5">
        <Section title="Your data">
          <SettingRow label="Export account data" description="Download everything Tradexa stores about you.">
            <Button variant="secondary" onClick={() => toast("Your data export is prepared and downloaded when connected to the backend.", "info")}>
              <Download className="h-4 w-4" /> Request export
            </Button>
          </SettingRow>
          <SettingRow label="Delete personal data" description="Permanently erase your personal data. This cannot be undone.">
            <Button className="bg-none bg-loss text-white shadow-none hover:brightness-110" onClick={() => setConfirmDelete(true)}>
              Delete data
            </Button>
          </SettingRow>
        </Section>

        <Section title="Cookies">
          <SettingRow label="Functional cookies" description="Required to remember your settings and session.">
            <Switch label="Functional cookies" checked={p.functionalCookies} onChange={(v) => set({ functionalCookies: v })} />
          </SettingRow>
          <SettingRow label="Marketing cookies" description="Used to measure and improve outreach. Off by default.">
            <Switch label="Marketing cookies" checked={p.marketingCookies} onChange={(v) => set({ marketingCookies: v })} />
          </SettingRow>
        </Section>

        <Section title="Analytics">
          <SettingRow label="Product analytics" description="Help improve Tradexa with anonymous usage analytics.">
            <Switch label="Product analytics" checked={p.analytics} onChange={(v) => set({ analytics: v })} />
          </SettingRow>
          <SettingRow label="Share anonymized usage data" description="Contribute aggregate, non-identifying data.">
            <Switch label="Share usage data" checked={p.shareUsageData} onChange={(v) => set({ shareUsageData: v })} />
          </SettingRow>
        </Section>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        danger
        title="Delete personal data?"
        description="This permanently erases your personal data. Your trading configuration is unaffected."
        confirmLabel="Delete data"
        confirmPhrase="DELETE"
        onConfirm={() => toast("Personal data deletion requested.", "success")}
        onClose={() => setConfirmDelete(false)}
      />
    </>
  );
}
