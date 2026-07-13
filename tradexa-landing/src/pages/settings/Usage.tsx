import { useCallback, useEffect, useState } from "react";
import {
  Activity, Radio, Server, Timer, Cpu, MemoryStick, Gauge, LayoutGrid, LogIn,
  type LucideIcon,
} from "lucide-react";
import { SettingsHeader, NotConnected } from "@/components/settings/primitives";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { hubConfig, hubFetch } from "@/lib/hub";

/** Real engine telemetry (GET /system/status). */
interface SystemStatus {
  mode: string;
  data_source: string;
  engine_running: boolean;
  strategy: string;
  symbols: string[];
  timeframe: string;
  bars_processed: number;
  signals: number;
  trades: number;
  uptime_s: number;
  trading_state: string;
}

function fmtUptime(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export default function Usage() {
  const signedIn = hubConfig() !== null;
  const [st, setSt] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!hubConfig()) return;
    hubFetch<SystemStatus>("/system/status")
      .then((d) => {
        setSt(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
    if (!signedIn) return;
    const iv = window.setInterval(load, 5000);
    return () => window.clearInterval(iv);
  }, [load, signedIn]);

  const live = signedIn && st !== null;

  // Real values from the engine; "—" where no backend metric exists (never invented).
  const tiles: { label: string; icon: LucideIcon; value: string; sub: string }[] = [
    { label: "Trades executed", icon: Activity, value: live ? String(st.trades) : "—", sub: live ? "this engine run" : "not connected" },
    { label: "Signals generated", icon: Radio, value: live ? String(st.signals) : "—", sub: live ? "this engine run" : "not connected" },
    { label: "Bars processed", icon: LayoutGrid, value: live ? String(st.bars_processed) : "—", sub: live ? `${st.symbols.length} symbols · ${st.timeframe}` : "not connected" },
    { label: "Bot uptime", icon: Timer, value: live ? fmtUptime(st.uptime_s) : "—", sub: live ? (st.engine_running ? "engine running" : "engine stopped") : "not connected" },
    { label: "API requests", icon: Server, value: "—", sub: "no metrics backend" },
    { label: "Storage", icon: Server, value: "—", sub: "no metrics backend" },
    { label: "CPU", icon: Cpu, value: "—", sub: "no metrics backend" },
    { label: "Memory", icon: MemoryStick, value: "—", sub: "no metrics backend" },
    { label: "Latency", icon: Gauge, value: "—", sub: "no metrics backend" },
  ];

  return (
    <>
      <SettingsHeader title="Usage" description="Live telemetry from your running bot and infrastructure." />

      {!signedIn ? (
        <div className="mb-5">
          <NotConnected
            icon={LogIn}
            title="Sign in to stream live telemetry"
            detail="Engine counters (trades, signals, bars, uptime) are operator-only. Sign in and reload this page."
          />
        </div>
      ) : error ? (
        <div className="mb-5">
          <NotConnected detail={`Engine unreachable (${error}) — values below pause until it responds.`} />
        </div>
      ) : (
        st && (
          <div className="mb-5 flex flex-wrap items-center gap-2 text-sm text-white/60">
            <Badge tone={st.engine_running ? "emerald" : "neutral"}>
              {st.engine_running ? "Engine running" : "Engine stopped"}
            </Badge>
            <Badge tone="gold">{st.mode}</Badge>
            <Badge tone="neutral">{st.strategy}</Badge>
            <Badge tone="neutral">{st.data_source}</Badge>
            <span className="text-[13px] text-white/35">refreshes every 5s</span>
          </div>
        )
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {tiles.map((t) => (
          <Card key={t.label} className="p-4">
            <t.icon className="mb-2 h-4 w-4 text-white/40" />
            <p className="tabular text-2xl font-bold tracking-tight text-white/85">{t.value}</p>
            <p className="mt-0.5 text-[11px] uppercase tracking-wider text-white/40">{t.label}</p>
            <p className="mt-1 text-[11px] text-white/25">{t.sub}</p>
          </Card>
        ))}
      </div>
    </>
  );
}
