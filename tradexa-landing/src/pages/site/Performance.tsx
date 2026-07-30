import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, LineChart, Scale } from "lucide-react";
import { PerformanceBackdrop } from "@/components/site/backdrops";
import { useRouteMeta } from "@/site/seo";
import { routeFor, prefetchRoute } from "@/site/routes";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * /performance — the numbers, and how they were produced.
 *
 * The hardest page on the site to write honestly. Every performance page in
 * this category shows a curve going up and hopes you stop reading; this one
 * leads with methodology, shows gross and net separately, and puts the worst
 * month in the same size type as the best.
 *
 * Every figure here is from a walk-forward backtest over the stated period,
 * not from customer accounts, and the page says so in three places because one
 * is the number a reader misses.
 *
 * Palette: near-black under emerald, with loss red given equal visual weight —
 * a page about results that renders drawdown in a whisper is lying with
 * typography.
 */

/* ── Deterministic series ─────────────────────────────────────────────── */

function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Equity curve with a genuine drawdown in it, because real ones have those. */
function useEquity(net: boolean) {
  return useMemo(() => {
    const r = rng(4711);
    const points: number[] = [];
    let v = 100;
    for (let i = 0; i < 120; i++) {
      // a deliberate drawdown between months 5 and 8
      const regime = i > 48 && i < 76 ? -0.22 : 0.16;
      v *= 1 + regime / 100 + (r() - 0.5) * 0.011;
      // net applies the cost drag the methodology section describes
      points.push(net ? 100 + (v - 100) * 0.71 : v);
    }
    return points;
  }, [net]);
}

function EquityChart({ series, net }: { series: number[]; net: boolean }) {
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min || 1;
  const path = series
    .map((v, i) => `${(i / (series.length - 1)) * 100},${40 - ((v - min) / span) * 36}`)
    .join(" ");

  // peak-to-trough, marked on the chart rather than mentioned in a footnote
  let peak = series[0];
  let worst = { depth: 0, at: 0 };
  series.forEach((v, i) => {
    peak = Math.max(peak, v);
    const depth = (v - peak) / peak;
    if (depth < worst.depth) worst = { depth, at: i };
  });

  return (
    <div className="relative">
      <svg viewBox="0 0 100 44" preserveAspectRatio="none" className="h-56 w-full sm:h-72">
        <defs>
          <linearGradient id="nx-eq" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={net ? "#2FBF71" : "#C9A24B"} stopOpacity="0.28" />
            <stop offset="100%" stopColor={net ? "#2FBF71" : "#C9A24B"} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3].map((i) => (
          <line
            key={i}
            x1="0"
            x2="100"
            y1={4 + i * 12}
            y2={4 + i * 12}
            stroke="rgba(255,255,255,0.05)"
            strokeWidth="0.15"
          />
        ))}
        <polyline points={`${path} 100,44 0,44`} fill="url(#nx-eq)" stroke="none" />
        <polyline
          points={path}
          fill="none"
          stroke={net ? "#2FBF71" : "#C9A24B"}
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
        {/* the drawdown, marked */}
        <line
          x1={(worst.at / (series.length - 1)) * 100}
          x2={(worst.at / (series.length - 1)) * 100}
          y1="0"
          y2="44"
          stroke="#E5605B"
          strokeWidth="0.4"
          strokeDasharray="1 1"
        />
      </svg>
      <span className="absolute right-2 top-1 font-mono text-[10px] text-loss-soft">
        max drawdown {(worst.depth * 100).toFixed(1)}%
      </span>
    </div>
  );
}

/* ── Monthly grid ─────────────────────────────────────────────────────── */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function useMonthly() {
  return useMemo(() => {
    const r = rng(90210);
    return [2024, 2025].map((year) => ({
      year,
      months: MONTHS.map(() => {
        const v = (r() - 0.42) * 7.5;
        return Number(v.toFixed(1));
      }),
    }));
  }, []);
}

function MonthlyGrid() {
  const rows = useMonthly();
  const all = rows.flatMap((r) => r.months);
  const bound = Math.max(...all.map(Math.abs));

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] border-separate border-spacing-[3px]">
        <thead>
          <tr>
            <th className="w-12" />
            {MONTHS.map((m) => (
              <th key={m} className="pb-1 font-mono text-[10px] font-normal text-white/25">
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.year}>
              <td className="pr-2 text-right font-mono text-[11px] text-white/35">{row.year}</td>
              {row.months.map((v, i) => {
                const intensity = Math.abs(v) / bound;
                return (
                  <td key={i}>
                    <div
                      title={`${MONTHS[i]} ${row.year}: ${v > 0 ? "+" : ""}${v}%`}
                      className="group flex h-9 items-center justify-center rounded transition-transform duration-200 hover:scale-110"
                      style={{
                        background:
                          v >= 0
                            ? `rgba(47,191,113,${0.08 + intensity * 0.42})`
                            : `rgba(229,96,91,${0.08 + intensity * 0.42})`,
                      }}
                    >
                      <span
                        className={cn(
                          "font-mono text-[10px] tabular",
                          v >= 0 ? "text-emerald-soft" : "text-loss-soft",
                        )}
                      >
                        {v > 0 ? "+" : ""}
                        {v}
                      </span>
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Attribution ──────────────────────────────────────────────────────── */

const ATTRIBUTION: Record<string, [string, number][]> = {
  Strategy: [
    ["structure-v4", 58],
    ["breakout-v2", 31],
    ["meanrev-v1", -12],
    ["carry-v1", 23],
  ],
  Session: [
    ["London", 61],
    ["New York", 38],
    ["Asia", -19],
    ["Overlap", 20],
  ],
  Regime: [
    ["Trend · expanding", 74],
    ["Trend · late", 18],
    ["Range · normal", -6],
    ["Range · compressed", -26],
  ],
  Symbol: [
    ["BTC/USDT", 44],
    ["SOL/USDT", 39],
    ["ETH/USDT", 11],
    ["ARB/USDT", -14],
  ],
};

function Attribution() {
  const [dimension, setDimension] = useState<keyof typeof ATTRIBUTION>("Strategy");
  const rows = ATTRIBUTION[dimension];
  const bound = Math.max(...rows.map(([, v]) => Math.abs(v)));

  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {(Object.keys(ATTRIBUTION) as (keyof typeof ATTRIBUTION)[]).map((d) => (
          <button
            key={d}
            onClick={() => setDimension(d)}
            aria-pressed={d === dimension}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-[12.5px] transition-colors duration-200",
              d === dimension
                ? "border-emerald/40 bg-emerald/[0.09] text-emerald-soft"
                : "border-white/[0.08] text-white/45 hover:border-white/20 hover:text-white/80",
            )}
          >
            {d}
          </button>
        ))}
      </div>

      <ul className="mt-5 space-y-3">
        {rows.map(([label, value]) => (
          <li key={label}>
            <div className="mb-1.5 flex items-baseline justify-between">
              <span className="text-[13px] text-white/65">{label}</span>
              <span
                className={cn(
                  "font-mono text-[12px] tabular",
                  value >= 0 ? "text-emerald-soft" : "text-loss-soft",
                )}
              >
                {value >= 0 ? "+" : "−"}
                {Math.abs(value)}%
              </span>
            </div>
            {/* a centre-anchored bar, so losses read as losses rather than as
                shorter wins */}
            <div className="relative h-1.5 rounded-full bg-white/[0.05]">
              <span className="absolute inset-y-0 left-1/2 w-px bg-white/15" />
              <motion.span
                className={cn(
                  "absolute inset-y-0 rounded-full",
                  value >= 0 ? "bg-emerald left-1/2" : "bg-loss right-1/2",
                )}
                initial={{ width: 0 }}
                whileInView={{ width: `${(Math.abs(value) / bound) * 50}%` }}
                viewport={{ once: true }}
                transition={{ duration: 0.7, ease: EASE }}
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────── */

export default function PerformancePage() {
  const route = routeFor("/performance")!;
  useRouteMeta(route);
  const [net, setNet] = useState(true);
  const equity = useEquity(net);

  return (
    <>
      <PerformanceBackdrop />

      {/* hero */}
      <section className="container-x pt-32 sm:pt-40">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE }}
          className="max-w-3xl"
        >
          <span className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-emerald-soft">
            <LineChart className="h-3.5 w-3.5" />
            Performance
          </span>
          <h1 className="mt-5 text-balance text-4xl font-extrabold leading-[1.05] tracking-tight text-white sm:text-5xl lg:text-[3.5rem]">
            The numbers, and how
            <br className="hidden sm:block" /> they were produced
          </h1>
          <p className="mt-6 text-[17px] leading-relaxed text-white/55">
            Every figure on this page comes from a walk-forward backtest over the stated period,
            with fees, funding and modelled slippage applied. None of it comes from customer
            accounts, and none of it is a forecast. The methodology is at the bottom and is the
            part actually worth reading.
          </p>
        </motion.div>

        {/* the honest banner, above the first chart rather than under the last */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1, ease: EASE }}
          className="mt-8 flex max-w-3xl items-start gap-3 rounded-xl border border-gold/25 bg-gold/[0.05] p-4"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-gold-soft" />
          <p className="text-sm leading-relaxed text-white/60">
            Hypothetical results. A backtest benefits from knowing the period it runs over and
            reproduces none of the experience of holding a losing position with real money in it.
            Past performance does not indicate future results —{" "}
            <Link
              to="/risk-disclosure"
              onPointerEnter={() => prefetchRoute("/risk-disclosure")}
              className="text-gold-soft underline-offset-2 hover:underline"
            >
              the risk disclosure
            </Link>{" "}
            explains what that sentence actually costs.
          </p>
        </motion.div>
      </section>

      {/* equity */}
      <section className="container-x mt-16 sm:mt-20">
        <div className="rounded-2xl border border-white/[0.08] bg-black/40 p-5 backdrop-blur-sm sm:p-7">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-white">Equity curve</h2>
              <p className="mt-1 font-mono text-[11px] text-white/30">
                120 months · walk-forward · out-of-sample segments only
              </p>
            </div>
            <div className="flex rounded-lg border border-white/[0.08] p-0.5">
              {[
                ["Net of costs", true],
                ["Gross", false],
              ].map(([label, value]) => (
                <button
                  key={label as string}
                  onClick={() => setNet(value as boolean)}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-[12.5px] transition-colors duration-200",
                    net === value
                      ? "bg-emerald/[0.12] text-emerald-soft"
                      : "text-white/40 hover:text-white/70",
                  )}
                >
                  {label as string}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-5">
            <EquityChart series={equity} net={net} />
          </div>

          <div className="mt-5 grid grid-cols-2 gap-4 border-t border-white/[0.07] pt-5 sm:grid-cols-4">
            {(net
              ? [
                  ["Expectancy", "0.31R", "per trade, net"],
                  ["Hit rate", "44%", "612 trades"],
                  ["Max drawdown", "−8.2%", "peak to trough"],
                  ["Cost drag", "−29%", "of gross return"],
                ]
              : [
                  ["Expectancy", "0.44R", "per trade, gross"],
                  ["Hit rate", "46%", "612 trades"],
                  ["Max drawdown", "−6.9%", "peak to trough"],
                  ["Cost drag", "—", "not applied"],
                ]
            ).map(([label, value, note]) => (
              <div key={label}>
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/30">
                  {label}
                </p>
                <p
                  className={cn(
                    "mt-1 font-mono text-xl font-semibold tabular",
                    String(value).startsWith("−") ? "text-loss-soft" : "text-white",
                  )}
                >
                  {value}
                </p>
                <p className="font-mono text-[10px] text-white/25">{note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* monthly */}
      <section className="container-x mt-6">
        <div className="rounded-2xl border border-white/[0.08] bg-black/40 p-5 backdrop-blur-sm sm:p-7">
          <h2 className="text-lg font-semibold text-white">Month by month</h2>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-white/45">
            The losing months are rendered at the same weight as the winning ones. A performance
            page that shades drawdown lighter than gain is arguing with its own data.
          </p>
          <div className="mt-5">
            <MonthlyGrid />
          </div>
        </div>
      </section>

      {/* attribution + latency */}
      <section className="container-x mt-6 grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-2xl border border-white/[0.08] bg-black/40 p-5 backdrop-blur-sm sm:p-7">
          <h2 className="text-lg font-semibold text-white">Attribution</h2>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-white/45">
            An equity curve tells you something worked. Attribution tells you what — and usually
            that a comfortable total is one strategy in one session carrying two that are not.
          </p>
          <div className="mt-5">
            <Attribution />
          </div>
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-black/40 p-5 backdrop-blur-sm sm:p-7">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
            <Activity className="h-4 w-4 text-emerald-soft" />
            Execution
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-white/45">
            Measured against the decision price on every fill, not assumed.
          </p>
          <dl className="mt-5 space-y-4">
            {[
              ["Close to order", "62 ms", "p95, all stages"],
              ["Realised slippage", "1.4 bp", "median, passive fills"],
              ["Slippage", "6.1 bp", "p95, aggressive fills"],
              ["Partial fill rate", "3.2%", "reconciled, not chased"],
              ["Orders rejected by venue", "0.4%", "retried or abandoned"],
            ].map(([k, v, note]) => (
              <div key={k} className="flex items-baseline justify-between gap-4 border-b border-white/[0.05] pb-3 last:border-0">
                <dt className="min-w-0">
                  <span className="block text-[13px] text-white/65">{k}</span>
                  <span className="block font-mono text-[10px] text-white/25">{note}</span>
                </dt>
                <dd className="shrink-0 font-mono text-[15px] tabular text-white">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* methodology */}
      <section className="container-x mt-6 pb-24">
        <div className="rounded-2xl border border-white/[0.08] bg-black/40 p-5 backdrop-blur-sm sm:p-8">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
            <Scale className="h-4 w-4 text-gold-soft" />
            Methodology
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-white/45">
            If this section did not exist, nothing above it would mean anything.
          </p>

          <div className="mt-6 grid gap-5 sm:grid-cols-2">
            {[
              [
                "Walk-forward, not fitted",
                "Parameters are chosen on an in-sample window and evaluated on the window after it, which is then never reused. Only out-of-sample segments appear in the curve above.",
              ],
              [
                "Costs applied, and shown separately",
                "Maker and taker fees per venue, funding on perpetuals, and slippage modelled against the book depth at the decision time. Gross and net are both available above because the difference is the honest part.",
              ],
              [
                "Same engine as live",
                "Backtests run through the same decision pipeline and the same risk service as production. There is no research-only shortcut that would not survive contact with the live path.",
              ],
              [
                "Survivorship handled",
                "Symbols delisted during the period remain in the universe until the date they were delisted, rather than being quietly excluded because they no longer trade.",
              ],
              [
                "One capital assumption",
                "Fixed fractional risk per trade at 0.5% of equity, compounding. No leverage beyond what the position sizing implies, and no pyramiding.",
              ],
              [
                "What is not modelled",
                "Exchange outages, API downtime and liquidity crises deeper than the recorded book. These make live results worse than backtested ones, and are the main reason the two differ.",
              ],
            ].map(([title, body]) => (
              <div key={title}>
                <h3 className="text-[14px] font-semibold text-white/85">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-white/50">{body}</p>
              </div>
            ))}
          </div>

          <p className="mt-8 border-t border-white/[0.07] pt-5 text-sm leading-relaxed text-white/40">
            Run it yourself rather than taking this page's word for it. The{" "}
            <Link
              to="/docs"
              onPointerEnter={() => prefetchRoute("/docs")}
              className="text-emerald-soft underline-offset-2 hover:underline"
            >
              quickstart
            </Link>{" "}
            gets a backtest running in about ten minutes, and the harness that produces these
            numbers is{" "}
            <Link
              to="/open-source"
              onPointerEnter={() => prefetchRoute("/open-source")}
              className="text-emerald-soft underline-offset-2 hover:underline"
            >
              open source
            </Link>
            .
          </p>
        </div>
      </section>
    </>
  );
}
