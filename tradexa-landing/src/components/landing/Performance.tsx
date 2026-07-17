import { Reveal } from "@/components/Reveal";
import { useCountUp } from "@/hooks/useCountUp";

interface Metric {
  value: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  label: string;
  sub: string;
}

const METRICS: Metric[] = [
  { value: 99.9, decimals: 1, suffix: "%", label: "Platform Uptime", sub: "Resilient, always-on infrastructure" },
  { value: 100, prefix: "<", suffix: "ms", label: "Execution", sub: "Order routing latency target" },
  { value: 24, suffix: "/7", label: "Risk Protected", sub: "Guards enforced around the clock" },
];

function MetricStat({ m }: { m: Metric }) {
  const { ref, value } = useCountUp(m.value, 1600, m.decimals ?? 0);
  return (
    <div className="text-center">
      <p className="tabular text-5xl font-extrabold tracking-tight text-white sm:text-6xl">
        {m.prefix}
        <span ref={ref} className="text-gold-gradient">
          {value.toLocaleString(undefined, {
            minimumFractionDigits: m.decimals ?? 0,
            maximumFractionDigits: m.decimals ?? 0,
          })}
        </span>
        {m.suffix}
      </p>
      <p className="mt-2 text-base font-semibold text-white">{m.label}</p>
      <p className="mt-1 text-sm text-white/45">{m.sub}</p>
    </div>
  );
}

export function Performance() {
  return (
    <section id="performance" className="section">
      <div className="container-x">
        <Reveal>
          <div className="surface relative overflow-hidden px-6 py-16 sm:px-12">
            <div className="pointer-events-none absolute inset-0 bg-radial-fade" />
            <div className="relative grid gap-12 sm:grid-cols-3">
              {METRICS.map((m, i) => (
                <Reveal key={m.label} delay={i * 0.12}>
                  <MetricStat m={m} />
                </Reveal>
              ))}
            </div>
            <p className="relative mt-12 text-center text-xs text-white/35">
              Figures reflect the platform&apos;s engineering targets and always-on design — not a
              guarantee of trading returns.
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
