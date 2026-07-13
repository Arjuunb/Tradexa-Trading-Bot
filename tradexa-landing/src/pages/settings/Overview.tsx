import { Link } from "react-router-dom";
import { ShieldCheck, User, Bell, SlidersHorizontal, ShieldAlert, Plug, ArrowUpRight, Lock } from "lucide-react";
import { SettingsHeader, Section } from "@/components/settings/primitives";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { useSettings } from "@/settings/store";

const QUICK = [
  { slug: "profile", label: "Profile", desc: "Name, email, timezone", icon: User },
  { slug: "security", label: "Security", desc: "Password, 2FA, sessions", icon: ShieldCheck },
  { slug: "notifications", label: "Notifications", desc: "Channels & alerts", icon: Bell },
  { slug: "trading", label: "Trading", desc: "Leverage, pairs, orders", icon: SlidersHorizontal },
  { slug: "risk", label: "Risk", desc: "Limits & circuit breaker", icon: ShieldAlert },
  { slug: "exchanges", label: "Exchanges", desc: "Connect your venues", icon: Plug },
];

export default function SettingsOverview() {
  const { settings, backendConnected } = useSettings();
  const { trading, risk, ai } = settings;

  const config = [
    { label: "Mode", value: "Paper", tone: "gold" as const },
    { label: "Preferred venue", value: trading.preferredExchange, tone: "neutral" as const },
    { label: "Default timeframe", value: trading.defaultTimeframe, tone: "neutral" as const },
    { label: "Risk / trade", value: `${risk.riskPerTrade}%`, tone: "neutral" as const },
    { label: "Daily loss limit", value: `${risk.dailyLossLimit}%`, tone: "neutral" as const },
    { label: "AI", value: ai.enabled ? `On · ${ai.model}` : "Off", tone: ai.enabled ? "emerald" as const : "neutral" as const },
  ];

  return (
    <>
      <SettingsHeader title="Settings" description="Manage your account, trading configuration, and the automation engine." />

      <div className="space-y-5">
        <Section
          title="Current configuration"
          description="A snapshot of the settings that govern the bot."
          action={
            <Badge tone={backendConnected ? "emerald" : "neutral"}>
              {backendConnected ? "Backend connected" : "Local (self-hosted)"}
            </Badge>
          }
        >
          <div className="grid grid-cols-2 gap-3 py-3 sm:grid-cols-3">
            {config.map((c) => (
              <div key={c.label} className="rounded-xl border border-line bg-ink-800/40 p-3">
                <p className="text-[11px] uppercase tracking-wider text-white/40">{c.label}</p>
                <p className="mt-1 text-sm font-semibold text-white">
                  <Badge tone={c.tone}>{c.value}</Badge>
                </p>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2 border-t border-line/60 py-3 text-[13px] text-white/50">
            <Lock className="h-3.5 w-3.5 text-gold" />
            Live trading is hard-locked. The engine runs in paper mode by design.
          </div>
        </Section>

        <div>
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-white/40">Jump to</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {QUICK.map((q) => (
              <Link key={q.slug} to={`/settings/${q.slug}`}>
                <Card interactive className="group flex items-center gap-3 p-4">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-gold/20 bg-gold/[0.08] text-gold">
                    <q.icon className="h-5 w-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-white">{q.label}</p>
                    <p className="truncate text-[13px] text-white/45">{q.desc}</p>
                  </div>
                  <ArrowUpRight className="h-4 w-4 text-white/30 transition group-hover:text-gold" />
                </Card>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
