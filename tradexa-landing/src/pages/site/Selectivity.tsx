import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, Minus, X } from "lucide-react";
import { SelectivityBackdrop } from "@/components/site/backdrops";
import { ConvictionGauge } from "@/components/site/selectivity/ConvictionGauge";
import { useRouteMeta } from "@/site/seo";
import { routeFor } from "@/site/routes";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * /selectivity — conviction before capital.
 *
 * Black and gold, and almost nothing else. Where /engine is instrumentation and
 * /live-trade is a workspace, this page is a case file: a single candidate at a
 * time, examined against nine checks, with the reasoning written out. The
 * restraint is the argument — a page about saying no should not be busy.
 */

interface Check {
  label: string;
  weight: number;
  /** 0–100 for this individual check. */
  score: number;
  note: string;
}

interface Setup {
  id: string;
  symbol: string;
  context: string;
  verdict: "accepted" | "rejected";
  headline: string;
  reasoning: string[];
  checks: Check[];
}

const SETUPS: Setup[] = [
  {
    id: "sol",
    symbol: "SOL/USDT",
    context: "15m · trend · expanding volatility",
    verdict: "accepted",
    headline: "Range high reclaimed, retested, and held.",
    reasoning: [
      "Higher-timeframe trend and the entry timeframe point the same way — the single condition most correlated with this strategy's winners.",
      "The retest held above prior resistance rather than through it, which puts the invalidation somewhere tight and defensible.",
      "Analogue recall found eleven similar setups averaging +0.8R. None of them are a guarantee; together they are a reason.",
      "Correlated exposure is light, so the position is sized at 0.68% of equity rather than reduced.",
    ],
    checks: [
      { label: "Trend agreement", weight: 0.16, score: 94, note: "4h and 15m aligned" },
      { label: "Structure quality", weight: 0.15, score: 88, note: "clean reclaim, one retest" },
      { label: "Volatility regime", weight: 0.12, score: 79, note: "expanding — strategy's domain" },
      { label: "Liquidity", weight: 0.11, score: 84, note: "resting size above" },
      { label: "Session", weight: 0.08, score: 72, note: "London open" },
      { label: "Correlation load", weight: 0.13, score: 81, note: "0.31 against book" },
      { label: "News proximity", weight: 0.09, score: 90, note: "no scheduled event" },
      { label: "Analogue recall", weight: 0.09, score: 76, note: "11 matches, +0.8R avg" },
      { label: "Risk headroom", weight: 0.07, score: 88, note: "day at −0.2% of −3.0%" },
    ],
  },
  {
    id: "eth",
    symbol: "ETH/USDT",
    context: "1h · range · compressed volatility",
    verdict: "rejected",
    headline: "The pattern is there. The conditions for it are not.",
    reasoning: [
      "The shape qualifies — this is a textbook compression break, and a discretionary trader would very likely take it.",
      "Volatility is compressed, and this strategy's edge in compression has been negative across the record. The pattern is not the edge; the pattern in the right regime is.",
      "Analogue recall found nine similar setups averaging −0.4R, six of them stopped within two candles.",
      "Nothing about the setup is wrong. It is simply not one this system has ever made money on.",
    ],
    checks: [
      { label: "Trend agreement", weight: 0.16, score: 51, note: "1h flat, 4h mixed" },
      { label: "Structure quality", weight: 0.15, score: 82, note: "clean compression" },
      { label: "Volatility regime", weight: 0.12, score: 24, note: "compressed — outside domain" },
      { label: "Liquidity", weight: 0.11, score: 58, note: "thin above" },
      { label: "Session", weight: 0.08, score: 44, note: "late Asia" },
      { label: "Correlation load", weight: 0.13, score: 62, note: "0.44 against book" },
      { label: "News proximity", weight: 0.09, score: 88, note: "no scheduled event" },
      { label: "Analogue recall", weight: 0.09, score: 22, note: "9 matches, −0.4R avg" },
      { label: "Risk headroom", weight: 0.07, score: 74, note: "day at −0.9% of −3.0%" },
    ],
  },
  {
    id: "arb",
    symbol: "ARB/USDT",
    context: "15m · chop · event window",
    verdict: "rejected",
    headline: "Scored well. Vetoed anyway.",
    reasoning: [
      "Structure and momentum both scored above their individual bars, and on score alone this would have been routed.",
      "It sits eleven minutes before a scheduled macro release, inside the blackout window the scheduler enforces.",
      "The risk service does not weigh that against the score. A blackout is a veto, and a veto is not a vote.",
      "The candidate is recorded with the rule that stopped it, so it appears in the journal as a decision rather than an absence.",
    ],
    checks: [
      { label: "Trend agreement", weight: 0.16, score: 78, note: "aligned" },
      { label: "Structure quality", weight: 0.15, score: 74, note: "acceptable" },
      { label: "Volatility regime", weight: 0.12, score: 66, note: "borderline" },
      { label: "Liquidity", weight: 0.11, score: 71, note: "adequate" },
      { label: "Session", weight: 0.08, score: 64, note: "New York" },
      { label: "Correlation load", weight: 0.13, score: 69, note: "0.38 against book" },
      { label: "News proximity", weight: 0.09, score: 4, note: "11 min to release · blackout" },
      { label: "Analogue recall", weight: 0.09, score: 58, note: "5 matches, +0.1R avg" },
      { label: "Risk headroom", weight: 0.07, score: 81, note: "day at −0.4% of −3.0%" },
    ],
  },
];

const THRESHOLD = 72;

function weighted(s: Setup) {
  return Math.round(s.checks.reduce((sum, c) => sum + c.score * c.weight, 0));
}

/**
 * The qualification checklist.
 *
 * Items resolve in sequence rather than all at once — the sequence is the
 * point, since a setup is disqualified by a specific check at a specific
 * moment, and a list that arrives fully-formed hides which one it was.
 */
function Checklist({ setup }: { setup: Setup }) {
  const reduced = useReducedMotion() ?? false;
  const [revealed, setRevealed] = useState(reduced ? setup.checks.length : 0);

  useEffect(() => {
    if (reduced) {
      setRevealed(setup.checks.length);
      return;
    }
    setRevealed(0);
    const id = window.setInterval(() => {
      setRevealed((n) => {
        if (n >= setup.checks.length) {
          window.clearInterval(id);
          return n;
        }
        return n + 1;
      });
    }, 140);
    return () => window.clearInterval(id);
  }, [setup.id, reduced, setup.checks.length]);

  return (
    <ul className="divide-y divide-white/[0.06]">
      {setup.checks.map((c, i) => {
        const shown = i < revealed;
        const state = c.score >= 70 ? "pass" : c.score >= 45 ? "marginal" : "fail";
        const Icon = state === "pass" ? Check : state === "marginal" ? Minus : X;
        return (
          <li key={c.label} className="py-2.5">
            <motion.div
              initial={false}
              animate={{ opacity: shown ? 1 : 0.18, x: shown ? 0 : -6 }}
              transition={{ duration: 0.3, ease: EASE }}
              className="flex items-center gap-3"
            >
              <span
                className={cn(
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-colors duration-300",
                  !shown
                    ? "border-white/10 text-transparent"
                    : state === "pass"
                      ? "border-gold/50 bg-gold/12 text-gold-soft"
                      : state === "marginal"
                        ? "border-white/15 bg-white/[0.04] text-white/40"
                        : "border-loss/40 bg-loss/10 text-loss-soft",
                )}
              >
                <Icon className="h-3 w-3" strokeWidth={3} />
              </span>

              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-[13px] text-white/80">{c.label}</span>
                  <span className="shrink-0 font-mono text-[11px] tabular text-white/45">
                    {shown ? c.score : "··"}
                  </span>
                </span>
                <span className="mt-1 flex items-center gap-2">
                  <span className="h-[3px] flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                    <motion.span
                      className={cn(
                        "block h-full rounded-full",
                        state === "pass" ? "bg-gold" : state === "marginal" ? "bg-white/30" : "bg-loss",
                      )}
                      initial={{ width: 0 }}
                      animate={{ width: shown ? `${c.score}%` : 0 }}
                      transition={{ duration: 0.5, ease: EASE }}
                    />
                  </span>
                  <span className="w-8 shrink-0 text-right font-mono text-[9px] text-white/20">
                    ×{c.weight.toFixed(2)}
                  </span>
                </span>
                <span className="mt-0.5 block truncate font-mono text-[10px] text-white/25">
                  {c.note}
                </span>
              </span>
            </motion.div>
          </li>
        );
      })}
    </ul>
  );
}

/** The decision flow — a vertical thread with one gate that has no override. */
function DecisionFlow({ setup }: { setup: Setup }) {
  const score = weighted(setup);
  const clearedBar = score >= THRESHOLD;
  const blackout = setup.id === "arb";

  const steps = [
    { label: "Candidate", detail: `${setup.symbol} · ${setup.context}`, state: "pass" as const },
    { label: "Nine checks", detail: `weighted to ${score}`, state: "pass" as const },
    {
      label: `Threshold · ${THRESHOLD}`,
      detail: clearedBar ? `${score} clears the bar` : `${score} is below the bar`,
      state: clearedBar ? ("pass" as const) : ("stop" as const),
    },
    {
      label: "Risk envelope",
      detail: blackout
        ? "event blackout · 11 min to release"
        : clearedBar
          ? "budget, exposure and correlation clear"
          : "not reached",
      state: blackout ? ("stop" as const) : clearedBar ? ("pass" as const) : ("skip" as const),
    },
    {
      label: setup.verdict === "accepted" ? "Routed" : "Declined",
      detail:
        setup.verdict === "accepted"
          ? "sized 0.68% equity · protective orders placed"
          : "recorded with the rule that stopped it",
      state: setup.verdict === "accepted" ? ("pass" as const) : ("stop" as const),
    },
  ];

  return (
    <ol className="relative space-y-4 pl-8">
      <span aria-hidden className="absolute bottom-3 left-[11px] top-3 w-px bg-gradient-to-b from-gold/40 via-gold/15 to-transparent" />
      {steps.map((s, i) => (
        <motion.li
          key={s.label}
          initial={{ opacity: 0, x: -8 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.4, delay: i * 0.07, ease: EASE }}
          className="relative"
        >
          <span
            className={cn(
              "absolute -left-8 top-1 flex h-[22px] w-[22px] items-center justify-center rounded-full border text-[10px]",
              s.state === "pass"
                ? "border-gold/50 bg-obsidian text-gold-soft"
                : s.state === "stop"
                  ? "border-loss/45 bg-obsidian text-loss-soft"
                  : "border-white/10 bg-obsidian text-white/20",
            )}
          >
            {s.state === "pass" ? "✓" : s.state === "stop" ? "✕" : "–"}
          </span>
          <p className={cn("text-sm font-medium", s.state === "skip" ? "text-white/30" : "text-white/85")}>
            {s.label}
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-white/35">{s.detail}</p>
        </motion.li>
      ))}
    </ol>
  );
}

export default function SelectivityPage() {
  const route = routeFor("/selectivity")!;
  useRouteMeta(route);

  const [activeId, setActiveId] = useState(SETUPS[0].id);
  const setup = SETUPS.find((s) => s.id === activeId)!;
  const score = weighted(setup);

  return (
    <>
      <SelectivityBackdrop />

      {/* ── Hero: an editorial statement, right-weighted ────────────────── */}
      <section className="container-x pt-32 sm:pt-40">
        <div className="grid gap-12 lg:grid-cols-[1fr_0.85fr] lg:items-center">
          <div>
            <motion.span
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.6 }}
              className="font-mono text-[11px] uppercase tracking-[0.28em] text-gold/70"
            >
              Selectivity
            </motion.span>

            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.06, ease: EASE }}
              className="mt-6 text-balance text-4xl font-extrabold leading-[1.06] tracking-[-0.02em] text-white sm:text-5xl lg:text-[3.6rem]"
            >
              It declines
              <br />
              <span className="text-gold-gradient">most of what it sees.</span>
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.14, ease: EASE }}
              className="mt-7 max-w-xl text-[17px] leading-relaxed text-white/55"
            >
              Roughly four hundred candidates are scored an hour and around nine become orders.
              The other three hundred and ninety-one are not failures of the system — they are
              the system. Every one is scored, explained and kept.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.2, ease: EASE }}
              className="mt-10 flex flex-wrap gap-x-10 gap-y-5 border-t border-gold/15 pt-6"
            >
              {[
                ["~2%", "of candidates routed"],
                ["9", "weighted qualifications"],
                ["100%", "rejections explained"],
              ].map(([v, k]) => (
                <div key={k}>
                  <p className="font-mono text-2xl font-semibold tabular text-gold-soft">{v}</p>
                  <p className="mt-1 text-[11px] uppercase tracking-[0.16em] text-white/30">{k}</p>
                </div>
              ))}
            </motion.div>
          </div>

          <motion.div
            initial={{ opacity: 0, scale: 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.9, delay: 0.12, ease: EASE }}
          >
            <ConvictionGauge score={score} threshold={THRESHOLD} verdict={setup.verdict} />
          </motion.div>
        </div>
      </section>

      {/* ── The case file ──────────────────────────────────────────────── */}
      <section className="container-x mt-24 sm:mt-32">
        {/* setup selector */}
        <div className="flex flex-wrap gap-2">
          {SETUPS.map((s) => {
            const active = s.id === activeId;
            return (
              <button
                key={s.id}
                onClick={() => setActiveId(s.id)}
                aria-pressed={active}
                className={cn(
                  "group relative overflow-hidden rounded-xl border px-4 py-3 text-left transition-all duration-300",
                  active
                    ? "border-gold/45 bg-gold/[0.07]"
                    : "border-white/[0.08] bg-white/[0.015] hover:border-gold/25 hover:bg-white/[0.03]",
                )}
              >
                <span className="flex items-center gap-2.5">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      s.verdict === "accepted" ? "bg-gold" : "bg-white/20",
                    )}
                  />
                  <span className={cn("text-sm font-medium", active ? "text-white" : "text-white/60")}>
                    {s.symbol}
                  </span>
                  <span className="font-mono text-[10px] tabular text-white/30">
                    {weighted(s)}
                  </span>
                </span>
                <span className="mt-1 block font-mono text-[10px] text-white/25">{s.context}</span>
              </button>
            );
          })}
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-[1fr_1.15fr]">
          {/* checklist */}
          <div className="rounded-2xl border border-white/[0.08] bg-black/40 p-5 backdrop-blur-sm sm:p-6">
            <div className="flex items-baseline justify-between border-b border-white/[0.07] pb-3">
              <h2 className="text-[13px] font-semibold uppercase tracking-[0.16em] text-white/50">
                Qualification
              </h2>
              <span className="font-mono text-[11px] text-white/30">9 checks · weighted</span>
            </div>
            <div className="mt-1">
              <Checklist setup={setup} />
            </div>
            <div className="mt-4 flex items-baseline justify-between border-t border-gold/15 pt-4">
              <span className="text-[11px] uppercase tracking-[0.18em] text-white/35">
                Weighted result
              </span>
              <span
                className={cn(
                  "font-mono text-2xl font-bold tabular",
                  score >= THRESHOLD ? "text-gold" : "text-white/45",
                )}
              >
                {score}
              </span>
            </div>
          </div>

          {/* reasoning */}
          <div className="rounded-2xl border border-white/[0.08] bg-black/40 p-5 backdrop-blur-sm sm:p-7">
            <AnimatePresence mode="wait">
              <motion.div
                key={setup.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.35, ease: EASE }}
              >
                <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-gold/70">
                  Engine reasoning
                </p>
                <h2 className="mt-3 text-balance text-2xl font-semibold leading-snug tracking-tight text-white">
                  {setup.headline}
                </h2>

                <ol className="mt-6 space-y-4">
                  {setup.reasoning.map((r, i) => (
                    <motion.li
                      key={r}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.4, delay: 0.1 + i * 0.09, ease: EASE }}
                      className="flex gap-4"
                    >
                      <span className="mt-0.5 font-mono text-[10px] tabular text-gold/50">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <p className="text-[15px] leading-relaxed text-white/60">{r}</p>
                    </motion.li>
                  ))}
                </ol>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </section>

      {/* ── Decision flow ──────────────────────────────────────────────── */}
      <section className="container-x mt-24 pb-24 sm:mt-32">
        <div className="grid gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
          <div className="lg:sticky lg:top-24">
            <span className="font-mono text-[11px] uppercase tracking-[0.24em] text-gold/70">
              Decision flow
            </span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-white sm:text-4xl">
              One gate has no override
            </h2>
            <p className="mt-4 max-w-md leading-relaxed text-white/55">
              A high score is permission to be considered, not permission to trade. The risk
              envelope is checked after the threshold and its verdict is final — which is why the
              third example on this page scored well enough and still did not happen.
            </p>
            <p className="mt-4 max-w-md leading-relaxed text-white/40">
              Rejections are written to the journal with the rule that produced them. Over a
              month that record is more useful than the trades: it is the only place you can see
              what the system nearly did.
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.08] bg-black/40 p-6 backdrop-blur-sm sm:p-8">
            <p className="mb-6 font-mono text-[10px] uppercase tracking-[0.18em] text-white/30">
              {setup.symbol} · {setup.context}
            </p>
            <DecisionFlow setup={setup} />
          </div>
        </div>
      </section>
    </>
  );
}
