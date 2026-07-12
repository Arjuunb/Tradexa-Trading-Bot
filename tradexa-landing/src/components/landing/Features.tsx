import { motion } from "framer-motion";
import {
  BrainCircuit,
  ShieldCheck,
  History,
  Radio,
  NotebookText,
  Building2,
  type LucideIcon,
} from "lucide-react";
import { Reveal, SectionHeading } from "@/components/Reveal";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";

interface Feature {
  icon: LucideIcon;
  title: string;
  body: string;
  points?: string[];
  exchanges?: { name: string; soon?: boolean }[];
  span?: boolean;
}

const FEATURES: Feature[] = [
  {
    icon: BrainCircuit,
    title: "AI Strategy Engine",
    body: "Automatically detects market structure, trend shifts and confirmations — and executes only high-quality setups.",
    span: true,
  },
  {
    icon: ShieldCheck,
    title: "Risk Management",
    body: "Discipline enforced on every trade, before capital is ever exposed.",
    points: ["Maximum daily loss", "Position sizing", "Stop loss", "Take profit", "Trailing stop"],
  },
  {
    icon: History,
    title: "Backtesting",
    body: "Run your strategies against years of historical data before risking a single dollar.",
  },
  {
    icon: Radio,
    title: "Live Monitoring",
    body: "See everything as it happens.",
    points: ["Real-time logs", "Performance", "Positions", "PnL"],
  },
  {
    icon: NotebookText,
    title: "Trade Journal Integration",
    body: "Every completed trade flows automatically into the Tradexa Journal for review and coaching.",
  },
  {
    icon: Building2,
    title: "Exchange Support",
    body: "Connect the venues you already trade on.",
    exchanges: [
      { name: "Binance" },
      { name: "Bybit" },
      { name: "OKX" },
      { name: "Hyperliquid", soon: true },
    ],
  },
];

export function Features() {
  return (
    <section id="features" className="section">
      <div className="container-x">
        <SectionHeading
          eyebrow="Capabilities"
          title="Everything an automated desk needs"
          subtitle="Purpose-built for traders who want speed and automation without giving up control or transparency."
        />

        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={(i % 3) * 0.08} className={cn(f.span && "lg:col-span-1")}>
              <Card interactive className="group h-full p-6">
                <div className="mb-5 inline-flex h-11 w-11 items-center justify-center rounded-xl border border-gold/20 bg-gold/[0.08] text-gold transition-transform duration-300 group-hover:scale-110">
                  <f.icon className="h-5 w-5" />
                </div>
                <h3 className="text-lg font-semibold text-white">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-white/55">{f.body}</p>

                {f.points && (
                  <ul className="mt-4 grid grid-cols-1 gap-1.5">
                    {f.points.map((p) => (
                      <li key={p} className="flex items-center gap-2 text-sm text-white/70">
                        <span className="h-1 w-1 rounded-full bg-gold" />
                        {p}
                      </li>
                    ))}
                  </ul>
                )}

                {f.exchanges && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {f.exchanges.map((e) => (
                      <Badge key={e.name} tone={e.soon ? "neutral" : "gold"}>
                        {e.name}
                        {e.soon && <span className="text-white/40">· Soon</span>}
                      </Badge>
                    ))}
                  </div>
                )}

                {/* gold hover underglow */}
                <motion.div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-gold/50 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
              </Card>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
