import { CreditCard, Server } from "lucide-react";
import { SettingsHeader, Section, SettingRow, NotConnected } from "@/components/settings/primitives";
import { Badge } from "@/components/ui/Badge";

export default function Billing() {
  return (
    <>
      <SettingsHeader title="Billing" description="Your plan and payment details." />

      <div className="space-y-5">
        <Section title="Current plan">
          <SettingRow label="Self-hosted · Free" description="You run TradeLogX Nexus on your own infrastructure. There is no subscription and no enforced usage limits.">
            <Badge tone="emerald">Active</Badge>
          </SettingRow>
          <div className="flex items-start gap-3 border-t border-line/60 py-3 text-[13px] text-white/50">
            <Server className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
            <p>Because this deployment is self-hosted, billing is not applicable — you control the compute and data directly.</p>
          </div>
        </Section>

        <Section title="Subscription & payments">
          <div className="py-3">
            <NotConnected icon={CreditCard} detail="No billing provider is connected in this self-hosted deployment. Subscriptions, payment methods and invoices would appear here on a managed plan." />
          </div>
        </Section>

        <Section title="Usage & limits">
          <SettingRow label="Plan limits" description="Self-hosted deployments have no platform-enforced trade, API or storage limits — you're bounded only by your own infrastructure.">
            <Badge tone="neutral">Unlimited</Badge>
          </SettingRow>
        </Section>
      </div>
    </>
  );
}
