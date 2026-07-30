import { useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Activity, Brain, CandlestickChart, Clock, Layers3, Wallet } from "lucide-react";
import { TerminalBackdrop } from "@/components/site/backdrops";
import { useTape } from "@/components/site/live/useTape";
import { CandleChart } from "@/components/site/live/CandleChart";
import {
  DecisionPanel,
  ExecutionTimeline,
  OrderBook,
  Panel,
  Positions,
  type Position,
} from "@/components/site/live/panels";
import { useRouteMeta } from "@/site/seo";
import { routeFor } from "@/site/routes";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * /live-trade — the execution terminal.
 *
 * The one page on the site with no marketing layout at all: no centred
 * headings, no cards on a bloom, no reveal-on-scroll. It is a workspace, and
 * the argument it makes is made by looking like one. Everything is monospace,
 * every panel is a hairline rectangle, and the only colour is the green and
 * red that money is denominated in.
 *
 * Every number is simulated and the page says so, twice — once in the status
 * bar and once at the foot. A trading interface that implies live capital
 * without being it is the one dishonesty this design cannot afford.
 */

const SYMBOLS = [
  { s: "BTC/USDT", tf: "15m" },
  { s: "SOL/USDT", tf: "15m" },
  { s: "ETH/USDT", tf: "1h" },
];

/** The scrolling tape across the top — pure texture, zero interaction. */
function Ticker() {
  const items = [
    ["BTC/USDT", "68,408.0", 0.42],
    ["ETH/USDT", "3,284.15", -0.18],
    ["SOL/USDT", "148.24", 1.36],
    ["ARB/USDT", "0.8412", -0.94],
    ["AVAX/USDT", "27.61", 0.22],
    ["OP/USDT", "1.7420", -0.51],
    ["LINK/USDT", "16.88", 0.77],
  ];
  const row = [...items, ...items];
  return (
    <div className="overflow-hidden border-y border-term-500/60 bg-black/50">
      <div className="flex w-max motion-safe:animate-tape-scroll">
        {row.map(([sym, px, chg], i) => (
          <span key={i} className="flex shrink-0 items-baseline gap-2 px-5 py-1.5 font-mono text-[10px]">
            <span className="text-white/40">{sym as string}</span>
            <span className="tabular text-white/70">{px as string}</span>
            <span className={cn("tabular", (chg as number) >= 0 ? "text-emerald-soft" : "text-loss-soft")}>
              {(chg as number) >= 0 ? "+" : ""}
              {(chg as number).toFixed(2)}%
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

export default function LiveTradePage() {
  const route = routeFor("/live-trade")!;
  useRouteMeta(route);

  const reduced = useReducedMotion() ?? false;
  // The tape is driven by whether the workspace is actually on screen, so
  // scrolling past the terminal stops the simulation rather than leaving four
  // panels re-rendering at 900ms below the fold.
  const workspaceRef = useRef<HTMLDivElement>(null);
  const { candles, price, changePct, bids, asks, epoch } = useTape(workspaceRef);
  const [symbol, setSymbol] = useState(SYMBOLS[0].s);

  // The open BTC position, placed inside the range the simulated tape covers
  // so its rules stay on the chart's axis instead of forcing it to zoom out.
  const entry = 68_050;
  const stop = 67_420;
  const target = 69_380;

  const positions: Position[] = [
    { symbol: "BTC/USDT", side: "LONG", size: "0.420", entry, mark: price, stop, target, strategy: "structure-v4" },
    { symbol: "SOL/USDT", side: "LONG", size: "12.40", entry: 148.22, mark: 149.86, stop: 143.1, target: 161.8, strategy: "breakout-v2" },
    { symbol: "ETH/USDT", side: "SHORT", size: "1.850", entry: 3_301.4, mark: 3_284.15, stop: 3_366.0, target: 3_180.0, strategy: "meanrev-v1" },
  ];

  const up = changePct >= 0;

  return (
    <>
      <TerminalBackdrop />

      {/* ── Hero: a status bar, not a headline ──────────────────────────── */}
      <section className="pt-20">
        <Ticker />

        <div className="container-x pt-10">
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, ease: EASE }}
            className="flex flex-wrap items-end justify-between gap-6"
          >
            <div>
              <span className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-emerald-soft">
                <span className="relative flex h-1.5 w-1.5">
                  {!reduced && (
                    <span className="absolute inline-flex h-full w-full rounded-full bg-emerald opacity-70 motion-safe:animate-ping-ring" />
                  )}
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald" />
                </span>
                session active · simulated
              </span>
              <h1 className="mt-4 text-4xl font-extrabold tracking-tight text-white sm:text-5xl">
                The terminal
              </h1>
              <p className="mt-3 max-w-lg leading-relaxed text-white/50">
                Chart, book, positions, reasoning and fills on one surface — the same layout the
                platform runs, driven here by a simulated tape so you can watch it work.
              </p>
            </div>

            <div className="flex items-end gap-8">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/25">
                  {symbol}
                </p>
                <p
                  className={cn(
                    "font-mono text-4xl font-bold tabular tracking-tight transition-colors",
                    up ? "text-emerald-soft" : "text-loss-soft",
                  )}
                >
                  {price.toFixed(1)}
                </p>
              </div>
              <div className="pb-1.5">
                <p
                  className={cn(
                    "font-mono text-lg tabular",
                    up ? "text-emerald-soft" : "text-loss-soft",
                  )}
                >
                  {up ? "▲" : "▼"} {Math.abs(changePct).toFixed(2)}%
                </p>
                <p className="font-mono text-[10px] text-white/25">session</p>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── The workspace ───────────────────────────────────────────────── */}
      <section className="container-x mt-8 pb-24">
        <motion.div
          ref={workspaceRef}
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.08, ease: EASE }}
          className="grid gap-2.5 lg:grid-cols-[minmax(0,1fr)_260px]"
        >
          {/* chart */}
          <Panel
            title="chart"
            icon={CandlestickChart}
            right={
              <div className="flex gap-1">
                {SYMBOLS.map((s) => (
                  <button
                    key={s.s}
                    onClick={() => setSymbol(s.s)}
                    className={cn(
                      "rounded px-2 py-0.5 font-mono text-[9px] transition-colors",
                      symbol === s.s
                        ? "bg-emerald/15 text-emerald-soft"
                        : "text-white/30 hover:bg-white/5 hover:text-white/60",
                    )}
                  >
                    {s.s.split("/")[0]}
                  </button>
                ))}
              </div>
            }
          >
            <div className="p-2">
              <CandleChart candles={candles} entry={entry} stop={stop} target={target} />
            </div>
          </Panel>

          {/* book */}
          <Panel
            title="order book"
            icon={Layers3}
            right={<span className="font-mono text-[9px] text-white/25">L2 · 9</span>}
          >
            <OrderBook bids={bids} asks={asks} price={price} />
          </Panel>

          {/* positions */}
          <Panel
            title="open positions"
            icon={Wallet}
            right={<span className="font-mono text-[9px] text-white/25">{positions.length} open</span>}
            className="lg:col-span-1"
          >
            <Positions positions={positions} />
          </Panel>

          {/* decision */}
          <Panel
            title="ai decision"
            icon={Brain}
            right={<span className="font-mono text-[9px] text-white/25">nexus-engine</span>}
          >
            <DecisionPanel epoch={epoch} price={price} />
          </Panel>

          {/* timeline spans the full width — it is the page's narrative */}
          <Panel
            title="execution timeline"
            icon={Clock}
            right={<span className="font-mono text-[9px] text-white/25">newest first</span>}
            className="lg:col-span-2"
          >
            <ExecutionTimeline epoch={epoch} />
          </Panel>
        </motion.div>

        {/* footer strip: what the terminal is actually doing */}
        <div className="mt-6 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Protective orders", "At the venue", "Stops and targets are placed on the exchange the instant a position opens — a dropped connection is not an unprotected position."],
            ["Slippage", "Measured per fill", "Every fill is compared against the price the decision was made at, so cost is a number rather than an assumption."],
            ["Partial fills", "Reconciled", "Unfilled remainder is re-evaluated against current conditions rather than chased."],
            ["Manual override", "Always available", "Flatten, halt or close any position from the terminal; every override is written to the audit log."],
          ].map(([title, tag, body], i) => (
            <motion.div
              key={title}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.45, delay: i * 0.05, ease: EASE }}
              className="rounded-lg border border-term-500/60 bg-term-800/60 p-4"
            >
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="text-[13px] font-semibold text-white/85">{title}</h3>
                <span className="shrink-0 font-mono text-[9px] uppercase tracking-wider text-emerald-soft/70">
                  {tag}
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-white/45">{body}</p>
            </motion.div>
          ))}
        </div>

        <p className="mt-6 flex items-center gap-2 font-mono text-[10px] text-white/25">
          <Activity className="h-3 w-3" />
          Every price, order and fill on this page is generated locally for illustration. No
          exchange is connected and no account is represented.
        </p>
      </section>
    </>
  );
}
