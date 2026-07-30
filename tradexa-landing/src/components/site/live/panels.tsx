import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import type { BookLevel } from "./useTape";
import { cn } from "@/lib/utils";

/** Terminal panel chrome: a title strip, a hairline border, no rounding drama. */
export function Panel({
  title,
  icon: Icon,
  right,
  children,
  className,
}: {
  title: string;
  icon?: LucideIcon;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-lg border border-term-500/70 bg-term-800/80 backdrop-blur-sm",
        className,
      )}
    >
      <header className="flex items-center gap-2 border-b border-term-500/70 bg-term-700/60 px-3 py-2">
        {Icon && <Icon className="h-3.5 w-3.5 shrink-0 text-white/35" />}
        <h3 className="font-mono text-[10px] uppercase tracking-[0.16em] text-white/45">{title}</h3>
        <div className="ml-auto shrink-0">{right}</div>
      </header>
      <div className="min-w-0 flex-1">{children}</div>
    </section>
  );
}

/**
 * Depth of book.
 *
 * Depth bars are anchored to the *inside* edge on both sides — asks growing
 * leftward, bids growing leftward too — because that is where the mid sits, and
 * the shape of the imbalance is the only thing a glance at a book is for.
 */
export function OrderBook({
  bids,
  asks,
  price,
}: {
  bids: BookLevel[];
  asks: BookLevel[];
  price: number;
}) {
  const maxSize = Math.max(...bids.map((b) => b.size), ...asks.map((a) => a.size));
  const bidTotal = bids.reduce((s, b) => s + b.size, 0);
  const askTotal = asks.reduce((s, a) => s + a.size, 0);
  const imbalance = bidTotal / (bidTotal + askTotal);

  const Level = ({ l, side }: { l: BookLevel; side: "bid" | "ask" }) => (
    <div className="relative flex items-center justify-between px-3 py-[3px] font-mono text-[10px]">
      <div
        className={cn("absolute inset-y-0 right-0", side === "bid" ? "bg-emerald/[0.13]" : "bg-loss/[0.13]")}
        style={{ width: `${(l.size / maxSize) * 100}%` }}
      />
      <span className={cn("relative tabular", side === "bid" ? "text-emerald-soft" : "text-loss-soft")}>
        {l.price.toFixed(1)}
      </span>
      <span className="relative tabular text-white/40">{l.size.toFixed(3)}</span>
    </div>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex justify-between border-b border-term-500/50 px-3 py-1.5 font-mono text-[9px] uppercase tracking-wider text-white/25">
        <span>price</span>
        <span>size</span>
      </div>
      <div>
        {asks.map((a) => (
          <Level key={a.price} l={a} side="ask" />
        ))}
      </div>
      <div className="flex items-baseline justify-between border-y border-term-500/70 bg-black/40 px-3 py-2">
        <span className="font-mono text-sm font-semibold tabular text-white">{price.toFixed(1)}</span>
        <span className="font-mono text-[9px] text-white/30">spread 1.5</span>
      </div>
      <div>
        {bids.map((b) => (
          <Level key={b.price} l={b} side="bid" />
        ))}
      </div>
      {/* imbalance meter */}
      <div className="mt-auto border-t border-term-500/50 px-3 py-2">
        <div className="mb-1 flex justify-between font-mono text-[9px] text-white/25">
          <span>bid {(imbalance * 100).toFixed(0)}%</span>
          <span>ask {((1 - imbalance) * 100).toFixed(0)}%</span>
        </div>
        <div className="flex h-1.5 overflow-hidden rounded-full bg-loss/25">
          <motion.div
            className="h-full bg-emerald"
            animate={{ width: `${imbalance * 100}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>
      </div>
    </div>
  );
}

export interface Position {
  symbol: string;
  side: "LONG" | "SHORT";
  size: string;
  entry: number;
  mark: number;
  stop: number;
  target: number;
  strategy: string;
}

export function Positions({ positions }: { positions: Position[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] border-collapse font-mono text-[10px]">
        <thead>
          <tr className="border-b border-term-500/50 text-left uppercase tracking-wider text-white/25">
            {["symbol", "side", "size", "entry", "mark", "pnl", "R", "strategy"].map((h) => (
              <th key={h} className="px-3 py-1.5 font-normal">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const dir = p.side === "LONG" ? 1 : -1;
            const pnlPct = ((p.mark - p.entry) / p.entry) * 100 * dir;
            const risk = Math.abs(p.entry - p.stop);
            const r = risk ? ((p.mark - p.entry) * dir) / risk : 0;
            const win = pnlPct >= 0;
            return (
              <tr key={p.symbol} className="border-b border-term-500/25 last:border-0 odd:bg-white/[0.015]">
                <td className="px-3 py-2 text-white/75">{p.symbol}</td>
                <td className="px-3 py-2">
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[9px]",
                      p.side === "LONG"
                        ? "bg-emerald/15 text-emerald-soft"
                        : "bg-loss/15 text-loss-soft",
                    )}
                  >
                    {p.side}
                  </span>
                </td>
                <td className="px-3 py-2 tabular text-white/50">{p.size}</td>
                <td className="px-3 py-2 tabular text-white/50">{p.entry.toFixed(1)}</td>
                <td className="px-3 py-2 tabular text-white/70">{p.mark.toFixed(1)}</td>
                <td className={cn("px-3 py-2 tabular", win ? "text-emerald-soft" : "text-loss-soft")}>
                  {win ? "+" : ""}
                  {pnlPct.toFixed(2)}%
                </td>
                <td className={cn("px-3 py-2 tabular", win ? "text-emerald-soft" : "text-loss-soft")}>
                  {r >= 0 ? "+" : ""}
                  {r.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-white/30">{p.strategy}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The AI decision panel.
 *
 * Its job on this page is narrower than on /engine: not to explain how the
 * decision is made, but to show that at any instant there *is* one, in words,
 * attached to a symbol and a number. The engine page owns the mechanism.
 */
export function DecisionPanel({ epoch, price }: { epoch: number; price: number }) {
  const decisions = useMemo(
    () => [
      {
        symbol: "BTC/USDT",
        action: "HOLD",
        score: 68,
        tone: "hold" as const,
        lines: [
          "Trend intact on 4h; 1h momentum flattening.",
          "Position already open — no add above 0.75% equity risk.",
        ],
      },
      {
        symbol: "SOL/USDT",
        action: "ROUTE LONG",
        score: 84,
        tone: "route" as const,
        lines: [
          "Range high reclaimed and retested; liquidity above.",
          "Risk envelope clear · sized 0.68% equity.",
        ],
      },
      {
        symbol: "ARB/USDT",
        action: "VETO",
        score: 61,
        tone: "veto" as const,
        lines: [
          "Score below the 72 bar for compressed volatility.",
          "Analogue recall: 3 similar setups, average −0.4R.",
        ],
      },
    ],
    [],
  );

  const d = decisions[epoch % decisions.length];
  const tone = {
    route: { cls: "border-emerald/40 bg-emerald/10 text-emerald-soft", ring: "#2FBF71" },
    hold: { cls: "border-line-strong bg-white/[0.04] text-white/60", ring: "#8A929C" },
    veto: { cls: "border-loss/40 bg-loss/10 text-loss-soft", ring: "#E5605B" },
  }[d.tone];

  return (
    <div className="p-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] text-white/70">{d.symbol}</span>
        <span className={cn("rounded border px-2 py-0.5 font-mono text-[9px] tracking-[0.12em]", tone.cls)}>
          {d.action}
        </span>
      </div>

      <div className="mt-3 flex items-center gap-3">
        <svg viewBox="0 0 44 44" className="h-11 w-11 shrink-0">
          <circle cx="22" cy="22" r="17" fill="none" stroke="#151C22" strokeWidth="5" />
          <motion.circle
            cx="22"
            cy="22"
            r="17"
            fill="none"
            stroke={tone.ring}
            strokeWidth="5"
            strokeLinecap="round"
            transform="rotate(-90 22 22)"
            strokeDasharray={2 * Math.PI * 17}
            animate={{ strokeDashoffset: 2 * Math.PI * 17 * (1 - d.score / 100) }}
            transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
          />
          <text x="22" y="26" textAnchor="middle" fill="#fff" style={{ fontSize: 13, fontWeight: 700 }}>
            {d.score}
          </text>
        </svg>
        <div className="min-w-0">
          <AnimatePresence mode="wait">
            <motion.ul
              key={d.symbol}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="space-y-1"
            >
              {d.lines.map((l) => (
                <li key={l} className="text-[11px] leading-relaxed text-white/50">
                  {l}
                </li>
              ))}
            </motion.ul>
          </AnimatePresence>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 border-t border-term-500/50 pt-2.5 font-mono text-[9px]">
        {[
          ["bar", "72"],
          ["mark", price.toFixed(0)],
          ["latency", "62 ms"],
        ].map(([k, v]) => (
          <div key={k}>
            <p className="text-white/25">{k}</p>
            <p className="tabular text-white/60">{v}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export interface TimelineEvent {
  t: string;
  kind: "eval" | "risk" | "order" | "fill" | "amend" | "veto";
  text: string;
}

const KIND_STYLE: Record<TimelineEvent["kind"], { dot: string; label: string }> = {
  eval: { dot: "bg-white/40", label: "text-white/45" },
  risk: { dot: "bg-signal", label: "text-signal-soft" },
  order: { dot: "bg-gold", label: "text-gold-soft" },
  fill: { dot: "bg-emerald", label: "text-emerald-soft" },
  amend: { dot: "bg-aqua", label: "text-aqua-soft" },
  veto: { dot: "bg-loss", label: "text-loss-soft" },
};

/**
 * Execution timeline.
 *
 * New events arrive at the top and push the rest down, because the question a
 * timeline answers is "what just happened", not "what happened first". The list
 * is capped so the panel cannot grow the page while you are looking at it.
 */
export function ExecutionTimeline({ epoch }: { epoch: number }) {
  const reduced = useReducedMotion() ?? false;
  const script: TimelineEvent[] = useMemo(
    () => [
      { t: "+0.00s", kind: "eval", text: "SOL/USDT close · conviction 84 · above bar" },
      { t: "+0.06s", kind: "risk", text: "envelope clear · 0.68% equity · corr 0.31" },
      { t: "+0.07s", kind: "order", text: "limit buy 12.4 SOL @ 148.22 · post-only" },
      { t: "+1.42s", kind: "fill", text: "filled 12.4 @ 148.24 · slip 1.3bp" },
      { t: "+1.44s", kind: "amend", text: "stop 143.10 · target 161.80 placed at venue" },
      { t: "+4.10s", kind: "eval", text: "ARB/USDT close · conviction 61" },
      { t: "+4.11s", kind: "veto", text: "below bar for compressed volatility · logged" },
    ],
    [],
  );

  const [events, setEvents] = useState<TimelineEvent[]>(() => script.slice(0, 4).reverse());

  useEffect(() => {
    if (reduced) return;
    setEvents((prev) => {
      const next = script[(epoch + 4) % script.length];
      return [{ ...next, t: stamp(epoch) }, ...prev].slice(0, 7);
    });
  }, [epoch, reduced, script]);

  return (
    <div className="relative p-3">
      {/* the spine */}
      <span aria-hidden className="absolute bottom-4 left-[18px] top-4 w-px bg-term-500" />
      <ul className="space-y-2.5">
        <AnimatePresence initial={false}>
          {events.map((e, i) => {
            const s = KIND_STYLE[e.kind];
            return (
              <motion.li
                key={`${e.t}-${e.text}-${i}`}
                layout
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: i === 0 ? 1 : 0.55 + Math.max(0, 0.45 - i * 0.09), y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                className="relative flex gap-3 pl-1"
              >
                <span className="relative mt-[5px] flex h-2 w-2 shrink-0 items-center justify-center">
                  <span className={cn("h-2 w-2 rounded-full", s.dot)} />
                  {i === 0 && !reduced && (
                    <span className={cn("absolute h-2 w-2 rounded-full motion-safe:animate-ping-ring", s.dot)} />
                  )}
                </span>
                <div className="min-w-0 font-mono text-[10px]">
                  <span className="text-white/20">{e.t}</span>
                  <span className={cn("ml-2 uppercase tracking-wider", s.label)}>{e.kind}</span>
                  <p className="mt-0.5 truncate text-white/50">{e.text}</p>
                </div>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>
    </div>
  );
}

function stamp(epoch: number) {
  const base = 9 * 3600 + 14 * 60;
  const s = base + epoch * 7;
  const hh = String(Math.floor(s / 3600) % 24).padStart(2, "0");
  const mm = String(Math.floor(s / 60) % 60).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}
