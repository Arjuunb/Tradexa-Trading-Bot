import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, LifeBuoy, MessageSquare, Search, ShieldAlert, Timer } from "lucide-react";
import { SupportBackdrop } from "@/components/site/backdrops";
import { useRouteMeta } from "@/site/seo";
import { routeFor, prefetchRoute } from "@/site/routes";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

interface Answer {
  q: string;
  a: string;
  topic: string;
  keywords: string[];
}

const ANSWERS: Answer[] = [
  {
    topic: "Connections",
    q: "My exchange key was rejected when I tried to connect it",
    a: "Almost always because the key carries withdrawal permission. That is refused at connection time by design — it is the structural reason a compromise of this platform cannot drain your account. Create a new key with trading enabled and withdrawal disabled, and allowlist our egress addresses if the venue supports it.",
    keywords: ["api key", "rejected", "withdrawal", "permission", "connect", "binance", "bybit"],
  },
  {
    topic: "Connections",
    q: "The venue shows as degraded and my orders are queuing",
    a: "The execution layer holds rather than retries into a venue that is rejecting or rate-limiting, because a retry storm makes an outage worse for everyone connected to it. Current venue health is on the status page. Positions already open keep their protective orders at the exchange throughout.",
    keywords: ["degraded", "outage", "queue", "orders", "stuck", "venue", "exchange down"],
  },
  {
    topic: "Risk",
    q: "The system stopped trading and I did not stop it",
    a: "Three things halt trading: a loss budget breach (daily, weekly or per-strategy), a scheduled blackout window, or a dependency being unreachable — the last of which fails closed deliberately. The risk console names which one and shows the number that triggered it. Open positions continue to be managed to their existing exits either way.",
    keywords: ["halted", "stopped", "not trading", "budget", "blackout", "fail closed", "paused"],
  },
  {
    topic: "Risk",
    q: "A trade I expected was vetoed",
    a: "Every veto is logged with the specific rule that fired — never a generic failure. The most common are correlation load against positions you already hold, a news blackout window, and the conviction score falling below the threshold for the current volatility regime. The decision record shows the full breakdown.",
    keywords: ["veto", "rejected trade", "no trade", "correlation", "threshold", "why"],
  },
  {
    topic: "Data",
    q: "My backtest results changed after an update",
    a: "Backtests run through the live engine, so an engine improvement changes historical results too. That is intentional — a backtest pinned to an old engine would tell you about a program you are no longer running. Every result stores the engine version it was produced with, and any decision can be replayed against its original stored inputs.",
    keywords: ["backtest", "changed", "different", "results", "version", "replay"],
  },
  {
    topic: "Data",
    q: "How do I export everything?",
    a: "Settings → Backup exports your full operating history — decisions, orders, fills, journal entries and configuration — in a machine-readable format, without asking anyone. There is no retention hold and no export fee. Closing the account does the same thing on the way out.",
    keywords: ["export", "download", "data", "backup", "leave", "gdpr", "csv"],
  },
  {
    topic: "Billing",
    q: "How do refunds and cancellation work?",
    a: "Cancel at any time from billing settings; access continues to the end of the period already paid for. Exchange fees, funding and spread are charged by the venue and are not ours to refund. If you were charged for something you did not use because of an outage on our side, tell us and we will fix it without a negotiation.",
    keywords: ["billing", "refund", "cancel", "subscription", "invoice", "charge"],
  },
  {
    topic: "Account",
    q: "I have lost access to my two-factor device",
    a: "Use a recovery code from when you enabled two-factor. If those are gone too, recovery requires proving control of the account's email plus a waiting period — we cannot shortcut it, and an account holding exchange credentials is exactly the wrong place to make an exception. Revoke your exchange keys at the venue in the meantime.",
    keywords: ["2fa", "two factor", "locked out", "recovery", "totp", "login"],
  },
];

const CHANNELS = [
  {
    icon: MessageSquare,
    title: "Support request",
    detail: "In-product, from any page. Carries your account context automatically, so nobody asks you to paste ids.",
    meta: "Best for anything account-specific",
  },
  {
    icon: ShieldAlert,
    title: "Security disclosure",
    detail: "A private channel with a named owner and a 24-hour acknowledgement target. Never open a public issue for a vulnerability.",
    meta: "Acknowledged within 24h",
  },
  {
    icon: LifeBuoy,
    title: "Community",
    detail: "Strategy discussion, configuration questions and other people who have hit the same thing. Not staffed as a support queue.",
    meta: "Peer answers, not guaranteed",
  },
];

const SEVERITY = [
  ["S1", "Trading is impaired or capital is at risk", "1 hour", "border-loss/40 text-loss-soft"],
  ["S2", "A feature is broken with no workaround", "4 hours", "border-gold/40 text-gold-soft"],
  ["S3", "Degraded, or a workaround exists", "1 business day", "border-white/15 text-white/60"],
  ["S4", "Question, or a feature request", "3 business days", "border-white/10 text-white/45"],
];

export default function SupportPage() {
  const route = routeFor("/support")!;
  useRouteMeta(route);

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(ANSWERS[0].q);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ANSWERS;
    const terms = q.split(/\s+/);
    return ANSWERS.filter((entry) => {
      const hay = [entry.q, entry.a, entry.topic, ...entry.keywords].join(" ").toLowerCase();
      return terms.every((t) => hay.includes(t));
    });
  }, [query]);

  return (
    <>
      <SupportBackdrop />

      <section className="container-x pt-32 sm:pt-40">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE }}
          className="max-w-2xl"
        >
          <span className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-gold/80">
            <LifeBuoy className="h-3.5 w-3.5" />
            Support center
          </span>
          <h1 className="mt-5 text-balance text-4xl font-extrabold leading-[1.05] tracking-tight text-white sm:text-5xl">
            Answers first, then a person
          </h1>
          <p className="mt-6 text-[17px] leading-relaxed text-white/55">
            The questions below are the ones that actually arrive, with the real answer rather
            than a link to a settings page. If yours is not here, the channels underneath reach a
            human — and the response targets are commitments, not aspirations.
          </p>
        </motion.div>

        {/* search */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1, ease: EASE }}
          className="mt-9 max-w-2xl"
        >
          <div className="flex items-center gap-3 rounded-xl border border-white/[0.1] bg-black/40 px-4 backdrop-blur-xl transition-colors focus-within:border-gold/40">
            <Search className="h-4.5 w-4.5 shrink-0 text-white/30" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              type="search"
              aria-label="Search support answers"
              placeholder="Search — “key rejected”, “halted”, “export”…"
              className="h-13 w-full min-w-0 bg-transparent py-3.5 text-[15px] text-white outline-none placeholder:text-white/25"
            />
          </div>
          <div className="sr-only" role="status" aria-live="polite">
            {query
              ? `${results.length} of ${ANSWERS.length} answers match ${query}`
              : `Showing all ${ANSWERS.length} answers`}
          </div>
        </motion.div>
      </section>

      {/* answers */}
      <section className="container-x mt-12">
        <AnimatePresence mode="popLayout">
          {results.length > 0 ? (
            <motion.ul key="list" layout className="max-w-3xl divide-y divide-white/[0.06] overflow-hidden rounded-2xl border border-white/[0.08] bg-black/30 backdrop-blur-sm">
              {results.map((entry) => {
                const isOpen = open === entry.q;
                return (
                  <li key={entry.q}>
                    <button
                      onClick={() => setOpen(isOpen ? null : entry.q)}
                      aria-expanded={isOpen}
                      className="flex w-full items-start gap-4 p-5 text-left transition-colors hover:bg-white/[0.03]"
                    >
                      <span className="mt-0.5 shrink-0 rounded border border-white/[0.1] px-2 py-0.5 font-mono text-[10px] text-white/40">
                        {entry.topic}
                      </span>
                      <span className="min-w-0 flex-1 text-[15px] text-white/85">{entry.q}</span>
                      <ChevronDown
                        className={cn(
                          "mt-0.5 h-4 w-4 shrink-0 text-white/25 transition-transform duration-300",
                          isOpen && "rotate-180 text-gold",
                        )}
                      />
                    </button>
                    <div
                      className="grid transition-[grid-template-rows] duration-400 ease-out motion-reduce:transition-none"
                      style={{ gridTemplateRows: isOpen ? "1fr" : "0fr" }}
                    >
                      <div className="overflow-hidden">
                        <p className="px-5 pb-5 text-[15px] leading-relaxed text-white/55">
                          {entry.a}
                        </p>
                      </div>
                    </div>
                  </li>
                );
              })}
            </motion.ul>
          ) : (
            <motion.div
              key="empty"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="max-w-3xl rounded-2xl border border-dashed border-white/[0.12] p-10 text-center"
            >
              <p className="text-white/70">
                Nothing matches “<span className="text-white">{query}</span>”.
              </p>
              <p className="mt-2 text-sm text-white/40">
                That is worth knowing — open a support request and the answer will end up on this
                page.
              </p>
              <button
                onClick={() => setQuery("")}
                className="mt-5 rounded-lg border border-gold/40 bg-gold/10 px-3.5 py-2 text-sm text-gold-soft transition hover:bg-gold/15"
              >
                Clear the search
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </section>

      {/* channels */}
      <section className="container-x mt-16">
        <h2 className="text-2xl font-bold tracking-tight text-white">Reaching a person</h2>
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          {CHANNELS.map((c) => (
            <div
              key={c.title}
              className="group rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-gold/25 hover:bg-white/[0.04]"
            >
              <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-gold/25 bg-gold/[0.08] text-gold-soft transition-transform duration-300 group-hover:scale-110">
                <c.icon className="h-4 w-4" />
              </span>
              <h3 className="mt-4 text-[15px] font-semibold text-white">{c.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/50">{c.detail}</p>
              <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.12em] text-white/25">
                {c.meta}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* severity */}
      <section className="container-x mt-8 pb-24">
        <div className="rounded-2xl border border-white/[0.08] bg-black/30 p-5 backdrop-blur-sm sm:p-7">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
            <Timer className="h-4 w-4 text-gold-soft" />
            Response targets
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-white/45">
            Time to a human response, not to resolution — because a fix time nobody can predict is
            not a commitment, and one that is quietly missed is worse than none.
          </p>

          <ul className="mt-5 space-y-2">
            {SEVERITY.map(([code, meaning, target, tone]) => (
              <li
                key={code}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-white/[0.06] bg-white/[0.015] px-4 py-3"
              >
                <span
                  className={cn(
                    "shrink-0 rounded border px-2 py-0.5 font-mono text-[11px] font-semibold",
                    tone,
                  )}
                >
                  {code}
                </span>
                <span className="min-w-0 flex-1 text-[14px] text-white/65">{meaning}</span>
                <span className="shrink-0 font-mono text-[12px] text-white/45">{target}</span>
              </li>
            ))}
          </ul>

          <p className="mt-6 border-t border-white/[0.07] pt-5 text-sm leading-relaxed text-white/40">
            If trading is impaired right now, check the{" "}
            <Link
              to="/status"
              onPointerEnter={() => prefetchRoute("/status")}
              className="text-gold-soft underline-offset-2 hover:underline"
            >
              status page
            </Link>{" "}
            first — an incident already being worked on is faster to read about than to report.
            For anything about how a decision was made, the{" "}
            <Link
              to="/docs"
              onPointerEnter={() => prefetchRoute("/docs")}
              className="text-gold-soft underline-offset-2 hover:underline"
            >
              documentation
            </Link>{" "}
            covers the vocabulary the answers use.
          </p>
        </div>
      </section>
    </>
  );
}
