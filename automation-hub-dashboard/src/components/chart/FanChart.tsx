// Monte Carlo equity fan: percentile bands (p5–p95 outer, p25–p75 inner) with a
// median line, a zero baseline, and a few faint bootstrap sample paths. Pure SVG,
// theme-aware via CSS vars. Input is R-denominated cumulative equity per step.
interface Bands { p5: number[]; p25: number[]; median: number[]; p75: number[]; p95: number[]; }

export default function FanChart({ bands, samples, height = 240 }:
  { bands: Bands; samples?: number[][]; height?: number }) {
  const n = bands.median.length;
  if (n < 2) return null;
  const W = 720, H = height, padX = 8, padTop = 12, padBot = 22;
  const allLo = Math.min(0, ...bands.p5);
  const allHi = Math.max(0, ...bands.p95);
  const span = allHi - allLo || 1;
  const x = (i: number) => padX + (i / (n - 1)) * (W - padX * 2);
  const y = (v: number) => padTop + (1 - (v - allLo) / span) * (H - padTop - padBot);

  const areaPath = (top: number[], bot: number[]) => {
    const up = top.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const dn = bot.map((_, i) => `L${x(bot.length - 1 - i).toFixed(1)},${y(bot[bot.length - 1 - i]).toFixed(1)}`).join("");
    return `${up}${dn}Z`;
  };
  const line = (a: number[]) => a.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" role="img" aria-label="Monte Carlo equity fan">
      {/* zero baseline */}
      <line x1={padX} x2={W - padX} y1={y(0)} y2={y(0)} stroke="var(--card-border)" strokeWidth="1" strokeDasharray="3 4" />
      {/* outer 5–95 band */}
      <path d={areaPath(bands.p95, bands.p5)} fill="var(--gold)" opacity="0.10" />
      {/* inner 25–75 band */}
      <path d={areaPath(bands.p75, bands.p25)} fill="var(--gold)" opacity="0.20" />
      {/* faint sample paths */}
      {(samples ?? []).slice(0, 16).map((s, i) => (
        <path key={i} d={line(s)} fill="none" stroke="var(--sky)" strokeWidth="0.6" opacity="0.16" />
      ))}
      {/* median */}
      <path d={line(bands.median)} fill="none" stroke="var(--gold)" strokeWidth="2" />
      {/* end labels */}
      <text x={W - padX} y={y(bands.p95[n - 1]) - 3} textAnchor="end" fontSize="10" fill="var(--dim)">p95 {bands.p95[n - 1].toFixed(0)}R</text>
      <text x={W - padX} y={y(bands.p5[n - 1]) + 11} textAnchor="end" fontSize="10" fill="var(--dim)">p5 {bands.p5[n - 1].toFixed(0)}R</text>
    </svg>
  );
}
