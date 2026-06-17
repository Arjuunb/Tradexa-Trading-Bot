# Tradexa Charts Kit (Apache ECharts)

A small, self-contained set of React + TypeScript chart components with a clean,
professional dark theme — the same pattern used in the trading-bot dashboard.
Copy this folder into Tradexa and you're done; nothing here depends on the bot.

## What's inside

| File | Purpose |
|------|---------|
| `chartTheme.ts` | All design tokens (colours, tooltip, axes, grid, gradients) — the single source of the look |
| `EChart.tsx` | The reusable wrapper — the only file that touches `echarts.init`. Inits once, updates reactively, resizes with its container, disposes on unmount |
| `AreaLine.tsx` | Smooth area/line chart (one or many series) |
| `BarChart.tsx` | Bar chart — `diverging` for green/red P&L, `horizontal` for ranked lists |
| `Doughnut.tsx` | Ring chart with an optional centred KPI |
| `Gauge.tsx` | Single-value gauge (exposure %, risk usage, confidence…) |
| `index.ts` | Barrel export |

## Install

```bash
npm install echarts
```

That's the only dependency (Apache ECharts ^5). Requires React 17+ and TypeScript.

Then drop this folder into your app, e.g. `src/charts/`, and (optionally) add a
path alias so you can `import { AreaLine } from "@/charts"`.

## Usage

```tsx
import { AreaLine, BarChart, Doughnut, Gauge } from "@/charts";

// Equity curve
<div style={{ height: 260 }}>
  <AreaLine
    labels={["Mon", "Tue", "Wed", "Thu", "Fri"]}
    series={[{ name: "Equity", data: [100, 140, 130, 180, 175], color: "#8b5cf6" }]}
    valueFormatter={(v) => `$${v.toLocaleString()}`}
  />
</div>

// Daily P&L (green/red)
<div style={{ height: 200 }}>
  <BarChart labels={["Mon","Tue","Wed"]} data={[120, -40, 80]} diverging />
</div>

// Win / loss with a centred KPI
<div style={{ height: 200 }}>
  <Doughnut
    data={[{ name: "Wins", value: 62, color: "#22c55e" }, { name: "Losses", value: 38, color: "#ef4444" }]}
    centerLabel="Win Rate" centerValue="62%" centerTone="pos"
  />
</div>

// Exposure gauge
<div style={{ height: 220 }}>
  <Gauge value={42} title="Exposure %" max={100} threshold={80} />
</div>
```

## Notes / tips

- **Always give the chart a sized parent.** ECharts fills its container, so wrap
  it in a `div` with an explicit height (or a flex/grid cell with a height).
- **Responsive for free** — the wrapper uses a `ResizeObserver`, so charts
  re-fit when the card resizes.
- **One place to restyle** — change `chartTheme.ts` (palette, tooltip, grid) and
  every chart updates. Match it to Tradexa's brand colours there.
- **Transparent background** keeps charts sitting flush inside cards; pair with
  your own card component for the polished look.
- **Smaller bundle (optional):** these import the full `echarts`. To shrink it,
  switch to tree-shaken imports (`echarts/core` + only the charts/components you
  use) inside `EChart.tsx`. Not required to get started.
```
