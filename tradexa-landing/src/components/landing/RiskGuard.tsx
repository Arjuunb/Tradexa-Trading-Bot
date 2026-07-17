import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Gauge, Layers, OctagonX, Percent } from "lucide-react";
import { Reveal, SectionHeading } from "@/components/Reveal";
import { cn } from "@/lib/utils";

/**
 * "Risk Guard" — the fifth landing animation. A live gauge of the day's risk
 * budget fills as (sample) losses accumulate; when it reaches the 3% daily-loss
 * cap, the kill switch trips and trading halts — then the day resets and the
 * loop restarts. Shows the guards doing their job, not just claiming to exist.
 * Illustrative sample data.
 */

const CAP = 3.0;            // daily-loss cap (%)
const EMERALD = "#2FBF71", GOLD = "#C8A94B", RED = "#E5605B";

// semicircle gauge geometry (r=74, centered at 92,92)
const ARC = "M 18 92 A 74 74 0 0 1 166 92";

export function RiskGuard() {
  const [p, setP] = useState(0);            // 0..1 cycle progress
  const raf = useRef<number | null>(null);
  const start = useRef<number | null>(null);
  const DURATION = 9000;

  useEffect(() => {
    const tick = (ts: number) => {
      if (!document.hidden) {
        if (start.current === null) start.current = ts;
        setP(((ts - start.current) % DURATION) / DURATION);
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, []);

  // risk used climbs to the cap by ~78% of the cycle, then holds (halted), then resets
  const used = Math.min(CAP, (p / 0.78) * CAP);
  const frac = used / CAP;
  const halted = frac >= 0.999;
  const color = halted ? RED : frac > 0.66 ? GOLD : EMERALD;
  const openTrades = halted ? 0 : Math.min(3, 1 + Math.floor(frac * 3));

  const guards = [
    { icon: Percent, label: "Position sizing", value: "1% risk per trade", tone: "ok" as const },
    { icon: Layers, label: "Exposure cap", value: `${openTrades} of 3 positions open`, tone: "ok" as const },
    { icon: Gauge, label: "Daily-loss budget", value: `−${used.toFixed(1)}% of −${CAP.toFixed(1)}% used`, tone: frac > 0.66 ? ("warn" as const) : ("ok" as const) },
    { icon: OctagonX, label: "Kill switch", value: halted ? "TRIPPED — entries blocked" : "Armed", tone: halted ? ("halt" as const) : ("ok" as const) },
  ];

  const TONE = {
    ok: "border-emerald/25 bg-emerald/[0.06] text-emerald",
    warn: "border-gold/30 bg-gold/[0.08] text-gold",
    halt: "border-loss/40 bg-loss/10 text-loss-soft",
  };

  return (
    <section id="risk-guard" className="section">
      <div className="container-x">
        <SectionHeading
          link="#risk-guard"
          eyebrow="Risk Guard"
          title="The bot that knows when to stop"
          subtitle="Hard limits are enforced in code — position size, exposure, and a daily-loss kill switch that halts trading before a bad day becomes a terrible one. Watch it trip."
        />

        <div className="mt-14 grid items-center gap-6 lg:grid-cols-[1fr_1fr] lg:gap-10">
          {/* gauge */}
          <Reveal>
            <div className={cn("rounded-2xl border bg-ink-800/40 p-6 transition-colors duration-500",
              halted ? "border-loss/40" : "border-line-strong")}>
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="font-medium text-white/70">Daily risk budget · paper</span>
                <span className={cn("rounded-full border px-2 py-0.5 font-mono transition-colors",
                  halted ? "border-loss/50 text-loss-soft" : "border-line-strong text-white/50")}>
                  {halted ? "trading halted" : "guards active"}
                </span>
              </div>
              <div className="relative mx-auto max-w-[320px]">
                <svg viewBox="0 0 184 104" className="w-full">
                  <path d={ARC} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={10} strokeLinecap="round" />
                  <path d={ARC} fill="none" stroke={color} strokeWidth={10} strokeLinecap="round"
                    pathLength={1} strokeDasharray={1} strokeDashoffset={1 - frac}
                    style={{ transition: "stroke 0.5s" }} />
                  {/* cap tick */}
                  <line x1={166} y1={92} x2={174} y2={92} stroke={RED} strokeWidth={2} opacity={0.7} />
                </svg>
                <div className="absolute inset-x-0 bottom-1 text-center">
                  <div className={cn("font-mono text-3xl font-bold tabular", halted ? "text-loss-soft" : "text-white")}>
                    −{used.toFixed(1)}%
                  </div>
                  <div className="text-[11px] text-white/40">of −{CAP.toFixed(1)}% daily cap</div>
                </div>
              </div>
              <motion.div initial={false} animate={{ opacity: halted ? 1 : 0, y: halted ? 0 : 6 }}
                transition={{ duration: 0.35 }}
                className="mt-4 rounded-xl border border-loss/40 bg-loss/10 px-4 py-2.5 text-center text-[13px] font-semibold text-loss-soft">
                Max daily loss reached — all new entries blocked until tomorrow.
              </motion.div>
            </div>
          </Reveal>

          {/* guard list */}
          <Reveal delay={0.1}>
            <ol className="flex flex-col gap-2.5">
              {guards.map((g) => {
                const Icon = g.icon;
                return (
                  <li key={g.label}
                    className={cn("flex items-center gap-3 rounded-xl border px-3.5 py-3 transition-colors duration-300", TONE[g.tone])}>
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-current">
                      <Icon className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold">{g.label}</div>
                      <div className="truncate font-mono text-[12px] opacity-75">{g.value}</div>
                    </div>
                  </li>
                );
              })}
              <p className="mt-1 text-xs text-white/35">
                Simulated day, illustrative numbers — the same guards run on every real cycle.
              </p>
            </ol>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
