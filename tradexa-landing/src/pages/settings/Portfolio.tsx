import { PieChart } from "lucide-react";
import { SettingsHeader, Section, SettingRow, NotConnected } from "@/components/settings/primitives";
import { Select } from "@/components/ui/Select";
import { Input } from "@/components/ui/Input";
import { useSettings } from "@/settings/store";
import type { Settings } from "@/settings/schema";

const CURRENCIES = ["USDT", "USDC", "USD", "BTC", "ETH"];

export default function Portfolio() {
  const { settings, update } = useSettings();
  const p = settings.portfolio;
  const set = (patch: Partial<Settings["portfolio"]>) => update("portfolio", patch);

  return (
    <>
      <SettingsHeader title="Portfolio" description="Base currency, targets and allocation. Autosaves." />

      <div className="space-y-5">
        <Section title="Preferences">
          <SettingRow label="Base currency" description="Everything is valued in this currency.">
            <div className="sm:w-40">
              <Select value={p.baseCurrency} options={CURRENCIES.map((c) => ({ value: c, label: c }))} onChange={(e) => set({ baseCurrency: e.target.value })} />
            </div>
          </SettingRow>
          <SettingRow label="Profit target" description="Optional target for the period. 0 = none.">
            <div className="relative w-40 sm:ml-auto">
              <Input type="number" min={0} value={String(p.profitTarget)} onChange={(e) => set({ profitTarget: Number(e.target.value) })} className="pr-14 text-right" />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-white/40">{p.baseCurrency}</span>
            </div>
          </SettingRow>
          <SettingRow label="Maximum allocation" description="Cap on total deployed capital.">
            <div className="relative w-40 sm:ml-auto">
              <Input type="number" min={0} max={100} value={String(p.maxAllocation)} onChange={(e) => set({ maxAllocation: Number(e.target.value) })} className="pr-8 text-right" />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-white/40">%</span>
            </div>
          </SettingRow>
        </Section>

        <Section title="Account balance">
          <div className="py-3">
            <NotConnected icon={PieChart} detail="Live balance appears here once an exchange is connected under Exchange Connections." />
          </div>
        </Section>

        <Section title="Asset allocation & synchronization">
          <div className="py-3">
            <NotConnected icon={PieChart} detail="Real-time allocation across your holdings appears here once an exchange is connected and portfolio sync is enabled." />
          </div>
        </Section>
      </div>
    </>
  );
}
