import { Activity, ShoppingCart, Radio, Server, HardDrive, Timer, Cpu, MemoryStick, Gauge, type LucideIcon } from "lucide-react";
import { SettingsHeader, NotConnected } from "@/components/settings/primitives";
import { Card } from "@/components/ui/Card";

const TILES: { label: string; icon: LucideIcon; unit?: string }[] = [
  { label: "Trades executed", icon: Activity },
  { label: "Orders today", icon: ShoppingCart },
  { label: "Signals generated", icon: Radio },
  { label: "API requests", icon: Server },
  { label: "Storage", icon: HardDrive, unit: "MB" },
  { label: "Bot uptime", icon: Timer },
  { label: "CPU", icon: Cpu, unit: "%" },
  { label: "Memory", icon: MemoryStick, unit: "%" },
  { label: "Latency", icon: Gauge, unit: "ms" },
];

export default function Usage() {
  return (
    <>
      <SettingsHeader title="Usage" description="Live telemetry from your running bot and infrastructure." />

      <div className="mb-5">
        <NotConnected detail="Live usage metrics stream here once VITE_API_BASE points at your running Tradexa backend. Values are shown empty rather than fabricated." />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {TILES.map((t) => (
          <Card key={t.label} className="p-4">
            <t.icon className="mb-2 h-4 w-4 text-white/40" />
            <p className="text-2xl font-bold tracking-tight text-white/70">
              —{t.unit && <span className="text-sm text-white/30"> {t.unit}</span>}
            </p>
            <p className="mt-0.5 text-[11px] uppercase tracking-wider text-white/40">{t.label}</p>
            <p className="mt-1 text-[11px] text-white/25">not connected</p>
          </Card>
        ))}
      </div>
    </>
  );
}
