import { useMemo } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

export type ScreenKind =
  | "decision"
  | "score"
  | "scanner"
  | "risk"
  | "equity"
  | "book"
  | "memory"
  | "analytics"
  | "feed";

/**
 * Product screenshots, drawn rather than captured.
 *
 * A PNG of the app would be a megabyte, would go stale the first time a colour
 * token moved, and would sit at one fixed resolution inside a card that has to
 * survive a 360px phone. These are built from the same tokens as the product,
 * so they scale, they stay in sync, and they cost a few hundred bytes each.
 *
 * They depict representative state — never live data, and never a specific
 * account.
 */

const TITLES: Record<ScreenKind, string> = {
  decision: "engine · decision record",
  score: "engine · conviction",
  scanner: "scanner · ranked watchlist",
  risk: "risk · envelope",
  equity: "lab · walk-forward",
  book: "execution · depth",
  memory: "memory · recall",
  analytics: "analytics · attribution",
  feed: "feed · live events",
};

/** Chrome shared by every mock: a window bar with three dots and a path. */
function Frame({ kind, children }: { kind: ScreenKind; children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-ink-800/80 shadow-card">
      <div className="flex items-center gap-2 border-b border-line bg-white/[0.02] px-3 py-2">
        <span className="flex gap-1.5">
          <span className="h-2 w-2 rounded-full bg-white/15" />
          <span className="h-2 w-2 rounded-full bg-white/15" />
          <span className="h-2 w-2 rounded-full bg-white/15" />
        </span>
        <span className="truncate font-mono text-[10px] tracking-tight text-white/35">
          {TITLES[kind]}
        </span>
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

function Row({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "gold" | "up" | "down" | "blue";
}) {
  const toneClass = {
    neutral: "text-white/70",
    gold: "text-gold-soft",
    up: "text-emerald-soft",
    down: "text-loss-soft",
    blue: "text-signal-soft",
  }[tone];
  return (
    <div className="flex items-baseline justify-between gap-3 py-[3px]">
      <span className="truncate text-[10px] text-white/35">{label}</span>
      <span className={cn("shrink-0 font-mono text-[11px] tabular", toneClass)}>{value}</span>
    </div>
  );
}

function Bar({ pct, tone = "gold" }: { pct: number; tone?: "gold" | "blue" | "up" | "down" }) {
  const bg = { gold: "bg-gold", blue: "bg-signal", up: "bg-emerald", down: "bg-loss" }[tone];
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-white/[0.06]">
      <motion.div
        className={cn("h-full rounded-full", bg)}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}

/** Deterministic pseudo-series so a mock looks the same on every render. */
function series(seed: number, n: number, drift: number) {
  const out: number[] = [];
  let v = 50;
  let s = seed;
  for (let i = 0; i < n; i++) {
    s = (s * 1103515245 + 12345) % 2147483648;
    v += ((s / 2147483648) - 0.45) * 9 + drift;
    out.push(v);
  }
  return out;
}

function Sparkline({ seed, drift, tone }: { seed: number; drift: number; tone: string }) {
  const pts = useMemo(() => {
    const s = series(seed, 44, drift);
    const min = Math.min(...s);
    const max = Math.max(...s);
    const span = max - min || 1;
    return s
      .map((v, i) => `${(i / (s.length - 1)) * 100},${34 - ((v - min) / span) * 30}`)
      .join(" ");
  }, [seed, drift]);

  return (
    <svg viewBox="0 0 100 36" preserveAspectRatio="none" className="h-16 w-full">
      <polyline points={pts} fill="none" stroke={tone} strokeWidth="1.1" vectorEffect="non-scaling-stroke" />
      <polyline
        points={`${pts} 100,36 0,36`}
        fill={tone}
        opacity="0.1"
        stroke="none"
      />
    </svg>
  );
}

export function ScreenMock({ kind, play = true }: { kind: ScreenKind; play?: boolean }) {
  const reduced = useReducedMotion() ?? false;
  const active = play && !reduced;

  return (
    <Frame kind={kind}>
      {kind === "decision" && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[11px] text-white/70">BTC/USDT · 4h</span>
            <span className="rounded-full border border-emerald/30 bg-emerald/10 px-2 py-0.5 font-mono text-[9px] text-emerald-soft">
              ROUTED
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-3">
            <Row label="conviction" value="81" tone="gold" />
            <Row label="regime" value="trend·exp" />
            <Row label="size" value="0.42 BTC" />
            <Row label="risk" value="0.75% eq" tone="blue" />
          </div>
          <div className="rounded-lg border border-line bg-black/30 p-2">
            <p className="text-[10px] leading-relaxed text-white/45">
              Higher-timeframe trend agrees, retest held above prior range high, liquidity
              above. Sized down 18% — correlated ETH position already open.
            </p>
          </div>
        </div>
      )}

      {kind === "score" && (
        <div className="space-y-2.5">
          {[
            ["trend agreement", 92, "gold"],
            ["structure quality", 78, "gold"],
            ["volatility regime", 64, "blue"],
            ["correlation load", 41, "down"],
            ["risk headroom", 88, "up"],
          ].map(([label, pct, tone]) => (
            <div key={label as string}>
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[10px] text-white/40">{label as string}</span>
                <span className="font-mono text-[10px] tabular text-white/60">{pct as number}</span>
              </div>
              <Bar pct={pct as number} tone={tone as "gold"} />
            </div>
          ))}
          <div className="mt-1 flex items-baseline justify-between border-t border-line pt-2">
            <span className="text-[10px] uppercase tracking-[0.16em] text-white/35">weighted</span>
            <span className="font-mono text-lg font-semibold tabular text-gold">73</span>
          </div>
        </div>
      )}

      {kind === "scanner" && (
        <div className="space-y-1">
          {[
            ["SOL/USDT", 84, "trend", "up"],
            ["BTC/USDT", 79, "trend", "up"],
            ["ETH/USDT", 61, "range", "neutral"],
            ["ARB/USDT", 48, "chop", "down"],
            ["AVAX/USDT", 33, "chop", "down"],
          ].map(([sym, score, regime, tone], i) => (
            <motion.div
              key={sym as string}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: active ? i * 0.05 : 0, duration: 0.3 }}
              className="flex items-center gap-2 rounded-md px-1.5 py-1 odd:bg-white/[0.02]"
            >
              <span className="w-3 font-mono text-[9px] text-white/25">{i + 1}</span>
              <span className="w-20 font-mono text-[10px] text-white/70">{sym as string}</span>
              <div className="flex-1">
                <Bar pct={score as number} tone={tone === "up" ? "gold" : tone === "down" ? "down" : "blue"} />
              </div>
              <span className="w-6 text-right font-mono text-[10px] tabular text-white/50">{score as number}</span>
              <span className="w-10 text-right font-mono text-[9px] text-white/25">{regime as string}</span>
            </motion.div>
          ))}
        </div>
      )}

      {kind === "risk" && (
        <div className="space-y-2">
          <div className="grid grid-cols-3 gap-2">
            {[
              ["daily", "-0.8%", "of -3.0%", 27],
              ["exposure", "2.1x", "of 4.0x", 52],
              ["corr load", "0.34", "of 0.60", 57],
            ].map(([k, v, of, pct]) => (
              <div key={k as string} className="rounded-lg border border-line bg-black/25 p-2">
                <p className="text-[9px] uppercase tracking-wider text-white/30">{k as string}</p>
                <p className="mt-0.5 font-mono text-sm tabular text-white">{v as string}</p>
                <p className="mb-1.5 font-mono text-[9px] text-white/25">{of as string}</p>
                <Bar pct={pct as number} tone="blue" />
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-loss/25 bg-loss/[0.07] px-2 py-1.5">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-loss" />
            <span className="font-mono text-[10px] text-loss-soft">VETO</span>
            <span className="truncate text-[10px] text-white/45">
              ADA/USDT long — correlation limit with SOL/USDT
            </span>
          </div>
        </div>
      )}

      {kind === "equity" && (
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[10px] text-white/35">in-sample</span>
            <span className="text-[10px] text-emerald-soft/70">out-of-sample</span>
          </div>
          <div className="relative">
            <Sparkline seed={7} drift={0.55} tone="#C9A24B" />
            <div className="absolute inset-y-0 right-0 w-1/3 border-l border-dashed border-emerald/30 bg-emerald/[0.04]" />
          </div>
          <div className="grid grid-cols-4 gap-2 border-t border-line pt-2">
            {[
              ["expectancy", "0.31R"],
              ["hit rate", "44%"],
              ["max dd", "-8.2%"],
              ["trades", "612"],
            ].map(([k, v]) => (
              <div key={k}>
                <p className="text-[9px] text-white/30">{k}</p>
                <p className="font-mono text-[11px] tabular text-white/80">{v}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {kind === "book" && (
        <div className="space-y-0.5 font-mono text-[10px]">
          {[
            [0.42, "68,412.5", "down"],
            [0.71, "68,411.0", "down"],
            [0.28, "68,409.5", "down"],
          ].map(([w, px], i) => (
            <div key={i} className="relative flex justify-between px-1 py-[2px]">
              <div className="absolute inset-y-0 right-0 bg-loss/10" style={{ width: `${(w as number) * 100}%` }} />
              <span className="relative text-loss-soft">{px as string}</span>
              <span className="relative tabular text-white/35">{((w as number) * 12).toFixed(2)}</span>
            </div>
          ))}
          <div className="my-1 flex justify-between border-y border-line px-1 py-1">
            <span className="text-white/70">68,408.0</span>
            <span className="text-white/30">spread 1.5</span>
          </div>
          {[
            [0.63, "68,406.5", "up"],
            [0.35, "68,405.0", "up"],
            [0.81, "68,403.5", "up"],
          ].map(([w, px], i) => (
            <div key={i} className="relative flex justify-between px-1 py-[2px]">
              <div className="absolute inset-y-0 right-0 bg-emerald/10" style={{ width: `${(w as number) * 100}%` }} />
              <span className="relative text-emerald-soft">{px as string}</span>
              <span className="relative tabular text-white/35">{((w as number) * 12).toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}

      {kind === "memory" && (
        <div className="space-y-2">
          <div className="rounded-lg border border-line bg-black/25 p-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] text-white/60">ETH/USDT · 12 Mar</span>
              <span className="font-mono text-[10px] text-loss-soft">-1.0R</span>
            </div>
            <p className="mt-1 text-[10px] leading-relaxed text-white/40">
              <span className="text-white/60">Mistake:</span> entered on the third retest after
              range compression — momentum had already been spent.
            </p>
            <p className="mt-1 text-[10px] leading-relaxed text-white/40">
              <span className="text-gold-soft/80">Lesson:</span> cap retests at two in compressed
              volatility.
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-gold/20 bg-gold/[0.05] px-2 py-1.5">
            <span className="font-mono text-[9px] uppercase tracking-wider text-gold-soft">recall</span>
            <span className="truncate text-[10px] text-white/45">
              3 analogues found · avg -0.4R · entry suppressed
            </span>
          </div>
        </div>
      )}

      {kind === "analytics" && (
        <div className="space-y-2">
          {[
            ["London session", 68, "up"],
            ["New York session", 41, "up"],
            ["Asia session", 22, "down"],
          ].map(([label, pct, tone]) => (
            <div key={label as string}>
              <div className="mb-1 flex justify-between">
                <span className="text-[10px] text-white/40">{label as string}</span>
                <span className={cn("font-mono text-[10px] tabular", tone === "up" ? "text-emerald-soft" : "text-loss-soft")}>
                  {tone === "up" ? "+" : "−"}
                  {pct as number}
                </span>
              </div>
              <Bar pct={pct as number} tone={tone === "up" ? "up" : "down"} />
            </div>
          ))}
          <p className="border-t border-line pt-2 text-[10px] leading-relaxed text-white/35">
            81% of net profit came from two symbols in one session.
          </p>
        </div>
      )}

      {kind === "feed" && (
        <div className="space-y-1 font-mono text-[10px]">
          {[
            ["09:14:02", "eval", "SOL/USDT scored 84 · above bar", "text-white/55"],
            ["09:14:02", "risk", "envelope ok · 0.75% equity", "text-signal-soft"],
            ["09:14:03", "order", "limit 148.22 · 12.4 SOL", "text-white/55"],
            ["09:14:07", "fill", "148.24 · slip 1.3bp", "text-emerald-soft"],
            ["09:18:00", "veto", "ARB/USDT · daily budget", "text-loss-soft"],
          ].map(([t, tag, msg, cls], i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: active ? i * 0.08 : 0, duration: 0.3 }}
              className="flex gap-2"
            >
              <span className="text-white/20">{t as string}</span>
              <span className="w-9 shrink-0 text-white/30">{tag as string}</span>
              <span className={cn("truncate", cls as string)}>{msg as string}</span>
            </motion.div>
          ))}
        </div>
      )}
    </Frame>
  );
}
