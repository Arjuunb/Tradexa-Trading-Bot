# Automation Hub — Dashboard (Phase 1)

A polished, dark-themed Automation Hub dashboard built with **React + TypeScript +
Apache ECharts**, using **mock data** only. This is the Phase 1 UI shell — no live
trading, no Tradexa integration, and the existing `bot/` engine is untouched.

## Run

```bash
cd automation-hub-dashboard
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production build to dist/
```

## Deploy (Vercel)

The repo-root `vercel.json` builds this app and serves it as the site:

```json
{ "builds": [{ "src": "automation-hub-dashboard/package.json",
              "use": "@vercel/static-build", "config": { "distDir": "dist" } }],
  "routes": [{ "handle": "filesystem" }, { "src": "/(.*)", "dest": "/index.html" }] }
```

Vercel runs `npm install && npm run build` in this folder and serves `dist/`.
Pushing to the production branch redeploys automatically. (This replaced the
earlier Python backtest-report deployment.)

## What's implemented

- **Left sidebar** — logo, 10 nav items (active state works), account summary card,
  market status.
- **Top header** — menu toggle, page title, Live status pill, notification/help/theme
  icons, user profile.
- **5 metric cards** — Total / Running / Paper / Live bots + Total P&L, each with an
  ECharts mini sparkline.
- **Equity Curve** — large ECharts area line (purple Equity + grey dashed Buy & Hold),
  tooltip, responsive resize.
- **Performance Overview** — metric grid with tiny ECharts sparklines.
- **My Bots** — Create Bot button (placeholder modal), All/Running/Paper/Live tabs that
  **filter** the list, and play/pause buttons that **update local mock status**.
- **Bot Activity feed**, **PnL Distribution** (ECharts doughnut + center total),
  **Risk Center** (data-driven progress bars), **Recent Alerts**.
- **Bottom ticker** — pair prices, server time, online dot.

## Structure

```
src/
├── App.tsx                 layout + state (bots, tabs, modal)
├── theme.ts                design tokens / status colors
├── data/mock.ts            ALL mock data (one place to swap for a real API later)
├── types.ts
└── components/
    ├── chart/EChart.tsx        reusable ECharts wrapper (resize + dispose)
    ├── chart/{Sparkline,EquityCurve,PnlDoughnut}.tsx
    ├── layout/{Sidebar,TopHeader,TickerBar}.tsx
    ├── cards/{MetricCards,PerformanceOverview,PnlDistribution}.tsx
    ├── bots/{MyBots,BotRow}.tsx
    ├── activity/ActivityFeed.tsx
    ├── risk/RiskCenter.tsx
    ├── alerts/RecentAlerts.tsx
    └── common/{Card,Icon,ProgressBar,Modal}.tsx
```

Every chart goes through the single `EChart` wrapper (dark styling, `ResizeObserver`,
disposes on unmount — no leaks, no console errors). Swap `src/data/mock.ts` for a real
API client to wire it to the backend in a later phase.
