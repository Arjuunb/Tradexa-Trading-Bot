import { useMemo } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Activity, CheckCircle2, Rss } from "lucide-react";
import { StatusBackdrop } from "@/components/site/backdrops";
import { useRouteMeta } from "@/site/seo";
import { routeFor, prefetchRoute } from "@/site/routes";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * /status — operational health.
 *
 * The one page a user opens when they are already unhappy, so it is built to
 * answer in three seconds: a headline verdict, a service list, and ninety days
 * of bars where a bad day is visible without reading a number.
 *
 * The data here is illustrative and the page says so at the top rather than in
 * a footnote — a status page that implies live monitoring while showing a
 * hard-coded array would be the single most misleading thing on this site.
 * Wire it to the real health endpoint before launch.
 */

type Health = "operational" | "degraded" | "outage";

interface Service {
  name: string;
  detail: string;
  health: Health;
  uptime: string;
}

const SERVICES: Service[] = [
  { name: "Decision engine", detail: "Eight-stage pipeline, all regions", health: "operational", uptime: "99.99%" },
  { name: "Risk service", detail: "Mandatory veto path", health: "operational", uptime: "100%" },
  { name: "Execution", detail: "Order routing and fills", health: "operational", uptime: "99.97%" },
  { name: "Market data", detail: "Feed normalisation and backfill", health: "degraded", uptime: "99.82%" },
  { name: "HTTP API", detail: "api.trade-logx.com", health: "operational", uptime: "99.99%" },
  { name: "Dashboard", detail: "Web application", health: "operational", uptime: "99.98%" },
];

const HEALTH_META: Record<Health, { label: string; dot: string; text: string }> = {
  operational: { label: "Operational", dot: "bg-emerald", text: "text-emerald-soft" },
  degraded: { label: "Degraded", dot: "bg-gold", text: "text-gold-soft" },
  outage: { label: "Outage", dot: "bg-loss", text: "text-loss-soft" },
};

interface Incident {
  date: string;
  title: string;
  severity: "resolved" | "degraded";
  body: string;
  duration: string;
}

const INCIDENTS: Incident[] = [
  {
    date: "2026-07-28",
    title: "Market data lag on one venue feed",
    severity: "degraded",
    duration: "41 minutes",
    body: "A venue websocket delivered candles with increasing delay without disconnecting, so failover did not trigger. Gap detection caught the staleness and strategies on that venue stood down rather than trading old data. Failover now considers staleness, not only disconnection.",
  },
  {
    date: "2026-07-11",
    title: "Elevated API latency, EU region",
    severity: "resolved",
    duration: "18 minutes",
    body: "A connection-pool exhaustion in the read path pushed p95 API latency above two seconds. Trading was unaffected — the decision path does not share that pool. Pool sizing is now derived from instance capacity rather than a fixed constant.",
  },
  {
    date: "2026-06-24",
    title: "Deliberate trading halt during a dependency failure",
    severity: "resolved",
    duration: "6 minutes",
    body: "The risk service became unreachable from the execution workers. The system failed closed and stopped placing orders, which is the intended behaviour. Open positions retained their venue-resident protective orders throughout. Root cause was a mesh certificate rotation that raced its own reload.",
  },
];

/** Ninety days of uptime bars, deterministic so the page never reshuffles. */
function useHistory(seed: number) {
  return useMemo(() => {
    let a = seed >>> 0;
    const rand = () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    return Array.from({ length: 90 }, () => {
      const r = rand();
      if (r > 0.985) return "outage" as Health;
      if (r > 0.955) return "degraded" as Health;
      return "operational" as Health;
    });
  }, [seed]);
}

function UptimeBars({ seed }: { seed: number }) {
  const days = useHistory(seed);
  return (
    <div className="flex h-8 items-end gap-[2px]">
      {days.map((d, i) => (
        <span
          key={i}
          title={`${90 - i} days ago · ${HEALTH_META[d].label}`}
          className={cn(
            "h-full flex-1 rounded-[1px] transition-all duration-200 hover:scale-y-110",
            d === "operational" && "bg-emerald/45 hover:bg-emerald",
            d === "degraded" && "bg-gold/60 hover:bg-gold",
            d === "outage" && "bg-loss/70 hover:bg-loss",
          )}
        />
      ))}
    </div>
  );
}

export default function StatusPage() {
  const route = routeFor("/status")!;
  useRouteMeta(route);

  const worst = SERVICES.some((s) => s.health === "outage")
    ? "outage"
    : SERVICES.some((s) => s.health === "degraded")
      ? "degraded"
      : "operational";
  const allGood = worst === "operational";

  return (
    <>
      <StatusBackdrop healthy={allGood} />

      {/* headline verdict */}
      <section className="container-x pt-32 sm:pt-40">
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: EASE }}
        >
          <span className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-white/35">
            <Activity className="h-3.5 w-3.5" />
            System status
          </span>

          <div
            className={cn(
              "mt-6 flex flex-wrap items-center gap-4 rounded-2xl border p-6 sm:p-7",
              allGood
                ? "border-emerald/30 bg-emerald/[0.06]"
                : "border-gold/30 bg-gold/[0.06]",
            )}
          >
            <span className="relative flex h-3 w-3 shrink-0">
              <span
                className={cn(
                  "absolute inline-flex h-full w-full rounded-full opacity-70 motion-safe:animate-ping-ring",
                  allGood ? "bg-emerald" : "bg-gold",
                )}
              />
              <span
                className={cn("relative inline-flex h-3 w-3 rounded-full", allGood ? "bg-emerald" : "bg-gold")}
              />
            </span>
            <div className="min-w-0">
              <h1 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">
                {allGood ? "All systems operational" : "One service degraded"}
              </h1>
              <p className="mt-1.5 text-sm text-white/50">
                {allGood
                  ? "Every service is within its normal operating range."
                  : "Market data is running behind on one venue feed. Trading on that venue has stood down rather than acting on stale candles."}
              </p>
            </div>
          </div>

          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-white/35">
            <span className="font-medium text-white/60">This page is not yet wired to live
            monitoring.</span>{" "}
            The service states and history below are illustrative. Until the health endpoint is
            connected, treat an incident here as an example of how one is reported rather than as
            a current fact.
          </p>
        </motion.div>
      </section>

      {/* services */}
      <section className="container-x mt-12">
        <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-black/40 backdrop-blur-sm">
          {SERVICES.map((s, i) => {
            const meta = HEALTH_META[s.health];
            return (
              <motion.div
                key={s.name}
                initial={{ opacity: 0, y: 8 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.4, delay: i * 0.05, ease: EASE }}
                className={cn(
                  "p-5 transition-colors hover:bg-white/[0.02] sm:p-6",
                  i > 0 && "border-t border-white/[0.06]",
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className={cn("h-2 w-2 shrink-0 rounded-full", meta.dot)} />
                    <div className="min-w-0">
                      <p className="text-[15px] font-medium text-white">{s.name}</p>
                      <p className="font-mono text-[11px] text-white/30">{s.detail}</p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-5">
                    <span className="font-mono text-[11px] tabular text-white/40">{s.uptime}</span>
                    <span className={cn("font-mono text-[11px]", meta.text)}>{meta.label}</span>
                  </div>
                </div>
                <div className="mt-4">
                  <UptimeBars seed={1000 + i * 37} />
                  <div className="mt-1.5 flex justify-between font-mono text-[9px] text-white/20">
                    <span>90 days ago</span>
                    <span>today</span>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </section>

      {/* incidents */}
      <section className="container-x mt-14 pb-24">
        <div className="grid gap-10 lg:grid-cols-[1fr_260px] lg:gap-16">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-white">Incident history</h2>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-white/45">
              Every incident gets a write-up naming the cause and the change made, including the
              ones where the system behaved correctly. A halt that worked is still an event worth
              explaining, because from the outside it looks identical to a failure.
            </p>

            <ol className="relative mt-8 space-y-6 pl-8">
              <span
                aria-hidden
                className="absolute bottom-2 left-[7px] top-2 w-px bg-gradient-to-b from-white/15 to-transparent"
              />
              {INCIDENTS.map((inc, i) => (
                <motion.li
                  key={inc.date}
                  initial={{ opacity: 0, x: -8 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, margin: "-60px" }}
                  transition={{ duration: 0.45, delay: i * 0.07, ease: EASE }}
                  className="relative"
                >
                  <span
                    className={cn(
                      "absolute -left-8 top-1.5 h-[15px] w-[15px] rounded-full border-2 border-[#050708]",
                      inc.severity === "degraded" ? "bg-gold" : "bg-emerald",
                    )}
                  />
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <time dateTime={inc.date} className="font-mono text-[11px] text-white/30">
                      {new Date(inc.date).toLocaleDateString("en-GB", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </time>
                    <span className="font-mono text-[11px] text-white/25">· {inc.duration}</span>
                  </div>
                  <h3 className="mt-1 text-[15px] font-semibold text-white">{inc.title}</h3>
                  <p className="mt-2 max-w-2xl text-sm leading-relaxed text-white/50">{inc.body}</p>
                </motion.li>
              ))}
            </ol>
          </div>

          <aside className="lg:sticky lg:top-24 lg:self-start">
            <div className="rounded-2xl border border-white/[0.08] bg-black/40 p-5">
              <h3 className="flex items-center gap-2 text-[14px] font-semibold text-white">
                <Rss className="h-4 w-4 text-emerald-soft" />
                Get notified
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-white/45">
                Incident notifications are delivered to the channels configured in your
                notification settings — email, Discord or a webhook — rather than requiring you to
                watch this page.
              </p>
              <Link
                to="/support"
                onPointerEnter={() => prefetchRoute("/support")}
                className="mt-4 inline-flex items-center gap-1.5 text-[13px] text-emerald-soft underline-offset-4 hover:underline"
              >
                Report something not shown here →
              </Link>
            </div>

            <div className="mt-3 rounded-2xl border border-white/[0.08] bg-black/40 p-5">
              <h3 className="flex items-center gap-2 text-[14px] font-semibold text-white">
                <CheckCircle2 className="h-4 w-4 text-emerald-soft" />
                What a halt means
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-white/45">
                The system fails closed. If the risk service is unreachable, trading stops rather
                than continuing unchecked — that is the design working, not breaking. Open
                positions keep their venue-resident protective orders throughout.
              </p>
              <Link
                to="/security"
                onPointerEnter={() => prefetchRoute("/security")}
                className="mt-4 inline-flex items-center gap-1.5 text-[13px] text-emerald-soft underline-offset-4 hover:underline"
              >
                How the architecture guarantees this →
              </Link>
            </div>
          </aside>
        </div>
      </section>
    </>
  );
}
