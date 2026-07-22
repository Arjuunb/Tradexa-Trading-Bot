# TradeLogX Nexus — UI/UX Design System Specification (UDS)

*Ninth blueprint in the series: `PRD` → `APP_FLOW_AUDIT` → `TRD` → `SAD` → `DDS` → `API_SPEC` → `TES` → `ADES` → **UDS**. This is the official design language for all future development — the single source of truth for color, type, spacing, components, charts, motion, and accessibility so any engineer can build a page **visually indistinguishable** from the rest of the platform.*

> **Version 1.0 · 2026-07-22 · Dark-first · Institutional-grade · Target stack: React + TypeScript + Tailwind + shadcn/ui + Radix**

---

## Reading guide — as-built vs. target (read first)

Consistent with the SAD/DDS/API/TES/ADES, every token/component is tagged: 🟢 **EXISTS** (a real value in the codebase) · 🟡 **PARTIAL** (exists but diverges across apps) · 🔴 **NEW/TARGET**.

**The pivotal finding this document reconciles:** *the two frontends do not share a styling engine today.*

| | `automation-hub-dashboard/` (the app) | `tradexa-landing/` (marketing/auth) |
|---|---|---|
| Styling | **No Tailwind.** One hand-written 65 KB `index.css` driven by CSS custom properties | **Tailwind 3.4** (`tailwind.config.ts`) |
| Components | Bespoke CSS-class components (`.btn`, `.card`, `.nav-item`) | Bespoke React primitives in `src/components/ui/` + `cn()` |
| Charts | **Apache ECharts 5.5** (canvas) + hand-rolled SVG + `reactflow` | none (framer-motion/CSS mockups) |
| Motion | CSS transitions | **framer-motion 11** |
| Icons | `lucide-react` ^1.23 | `lucide-react` ^0.427 |

**Neither app uses shadcn/ui or Radix today** — a repo-wide grep for `@radix-ui`, `class-variance-authority`, `cva(` returns zero. The brief asks for a system built on Tailwind + shadcn/ui + Radix; that is therefore the **target unification**, and this document specifies it while honestly grounding every token in the real values that exist now. Five concrete inconsistencies the system must resolve (all real, all verified) are catalogued in §20.

**What is genuinely strong today:** a coherent dark-first, gold-led + signal-blue identity; the N-monogram brand; a disciplined 8-pt spacing scale and type scale (as CSS vars); real accessibility primitives (sign-prefixed numbers, focus rings, route-level ErrorBoundary); a professional ECharts candlestick terminal; and a grouped-nav IA. **UI/UX readiness: 6.5 / 10** (§19) — a premium, consistent *within each app* experience whose main debt is **cross-app fragmentation and no shared component/token library**.

This spec's job: define **one** token set, **one** component library, **one** chart language, and **one** set of rules — so the dashboard and landing (and a future mobile app) render as one product.

---

## 1. Executive Summary

TradeLogX Nexus targets the visual caliber of **TradingView · Bloomberg Terminal · Binance · Coinbase Advanced · Stripe · Linear · Vercel · Notion**: modern, premium, **data-dense**, clean, and fast. The design system delivers that through:

- **One dark-first identity** — near-black ink surfaces, a warm gold lead, a signal-blue data accent, and semantic profit/loss greens/reds tuned for a trading floor.
- **One token layer** — colors, spacing (8-pt), type, radius, shadow, motion, z-index as named tokens, consumed identically by Tailwind (config) and CSS (variables), exported once to Figma.
- **One component library** — Tailwind + shadcn/ui + Radix primitives (accessible by default), themed by the tokens, replacing today's two bespoke sets.
- **One chart language** — ECharts, with a fixed palette, axis, crosshair, and marker vocabulary for candles, overlays, entry/exit/SL/TP, and replay.
- **One rulebook** — WCAG 2.2 AA, desktop-first responsive breakpoints, motion with reduced-motion respect, and quality/audit checklists that gate every new page.

**North-star acceptance test:** a new page built only from this document's tokens and components is indistinguishable from the rest of the app, passes the §17 quality checklist and §18 UX audit, and meets WCAG 2.2 AA — without a designer touching it.

---

## 2. Design Principles

1. **Clarity over decoration.** Every pixel serves comprehension; chrome recedes, data leads. (Bloomberg/Linear.)
2. **Consistency is a feature.** The same action looks and behaves the same everywhere; one component, one behavior.
3. **Minimal cognitive load.** Progressive disclosure — summary first, detail on demand (drill-down, expandable rows, the Observation Terminal).
4. **Information density with breathing room.** Dense tables and compact cards, but on a strict 8-pt rhythm so density never becomes noise.
5. **Speed is design.** Sub-16 ms interactions, virtualized tables, `animation:false` on the candle hot path; perceived performance is a first-class visual property.
6. **Accessibility is non-negotiable.** WCAG 2.2 AA; never rely on color alone (sign-prefixed numbers already prove this); full keyboard + screen-reader support.
7. **Professional restraint.** Premium = quiet. Gold is an accent, not a flood; motion is purposeful, never playful.
8. **Scalability.** Tokens + composable components mean new surfaces cost little and drift never accumulates.
9. **Dark-first.** The product lives in dark; it is the default and the priority. A light theme, if added, is derived from the same tokens — never a fork.

---

## 3. Brand Guidelines

### 3.1 Identity (🟢)
- **Name:** TradeLogX Nexus. **Wordmark:** "TradeLogX" (Inter, `15px`, `font-bold`) + "Nexus" (`tracking-[0.28em]`, gold at 80% opacity).
- **Mark — the N-monogram:** a two-tone "N" (silver ascent `#E9EEF3 → #AEB7C2`, gold descent `#E7C766 → #C6961F`) in a gold/steel ring, with an up-arrow tip and down-point — an up/down market move. Source: `public/nexus-mark.svg`; components `dashboard/src/components/common/Logo.tsx` and `landing/src/components/Logo.tsx` (`LogoMark` + `Logo`), viewBox `0 0 96 96`.
- **`theme-color`:** `#0a0a0c` (both apps).

### 3.2 Logo usage
- Clear space = 0.5× mark height on all sides. Minimum size 20 px (favicon set: 16/32/48, apple-touch 180, maskable 512).
- Use `LogoMark` alone in the collapsed sidebar rail and favicons; use the full lockup in the expanded sidebar header, auth screens, and marketing.
- **Don't:** recolor the mark, add effects beyond the shipped gradient, place on busy imagery without the ink scrim, or stretch. On light surfaces (rare), use the mono ink variant.
- **Consolidation (🔴):** ship **one** `Logo`/`LogoMark` package consumed by both apps (today it is duplicated with identical geometry).

### 3.3 Icons, illustration, imagery
- **Icons:** `lucide-react`, one library, `strokeWidth 1.9`, `size 18` in nav (§7.3). Pin **one version** across apps (today ^1.23 vs ^0.427 — §20).
- **Illustration:** none literal; "illustration" = data made beautiful (charts, the animated brain/engine visuals). No cartoon/mascot art.
- **Photography:** avoid stock photography; the product *is* the hero. Marketing screenshots use real UI on the `page-depth` gradient with the grid-lines overlay.
- **Marketing visuals:** gold-sheen gradient headlines (`text-gold-gradient`), glass cards, restrained motion (`fade-up`, `float`) — premium, quiet, never gimmicky.

---

## 4. Color System

Dark-first. Values below are the **canonical token set** — grounded in the real code, with the cross-app divergences (§20) resolved to one value each. The app is the reference; the landing's deeper gold becomes `gold-deep` for large marketing fills.

### 4.1 Core surfaces & brand (🟢 values, 🟡 unify)
| Token | Hex | Source / role |
|---|---|---|
| `--bg` | `#070708` | app canvas (dashboard `--bg`) |
| `--bg-2` | `#0D0D0F` | raised canvas |
| `--surface` / `--card-1` | `#121214` | card |
| `--surface-2` / `--card-2` | `#0E0E10` | inset card |
| `--surface-elevated` | `#17171A` | modal/popover |
| `--border` | `#232326` | default border |
| `--border-soft` | `#1A1A1D` | hairline |
| `--brand` / `--gold` | **`#EAB54F`** | primary brand (app gold); hover `#F2C66E` |
| `--gold-deep` | `#C9A24B` | large fills / marketing (landing gold) |
| `--gold-sheen` | `linear-gradient(135deg,#E7D89A,#C8A94B,#A98E3A)` | headline/CTA gradient |
| `--accent` / `--signal` | `#3E7BD6` | data/links (landing "signal blue"); app CTA `--sky #7CB9E8` |

### 4.2 Semantic (🟢/🟡)
| Token | Hex | Use |
|---|---|---|
| `--primary` | `#EAB54F` | primary actions, active nav |
| `--secondary` | `#7CB9E8` | secondary actions, links |
| `--accent` | `#3E7BD6` | AI/data highlights |
| `--success` / `--profit` / `--bullish` | `#22C55E` | wins, up, confirmations |
| `--danger` / `--loss` / `--bearish` | `#EF4444` | losses, down, destructive |
| `--warning` / `--risk` | `#EAB54F` | caution, risk (amber = gold family) |
| `--info` | `#3E7BD6` | neutral info |
| `--muted` | `#7C8798` | secondary text; `--dim #B0B8C4` primary-dim |
| `--text` | `#FFFFFF` | primary text |

### 4.3 Trading-specific (🟢)
| Token | Hex | Note |
|---|---|---|
| `--candle-up` | `#089981` | candlestick up (TradingView palette) |
| `--candle-down` | `#F23645` | candlestick down |
| **Rule** | — | candle colors are **intentionally distinct** from P&L green/red so a green candle in a losing trade never misreads. Documented, not a bug. |
| `--ema8/20/30/50` | `#22D3EE / #3B82F6 / #A855F7 / #F59E0B` | overlay lines |
| `--vwap` / `--supertrend` | `#EAB54F` | gold overlays |
| `--bollinger` | `#5B6478` | band |
| Heatmap | `#EF4444 → #7C8798 → #22C55E` | diverging loss↔neutral↔profit (correlation matrix, exposure) |
| AI | `#3E7BD6` | AI panels/confidence accents; confidence tones: VeryHigh/High → green, Medium → gold, Low/VeryLow → red |

### 4.4 Interaction states (🟢/🔴)
| State | Treatment |
|---|---|
| `hover` | +4% lightness on surfaces; nav hover = `rgba(124,185,232,0.08)` |
| `focus` | 2 px outline `rgba(234,181,79,0.55)` + 3 px `rgba(234,181,79,0.12)` ring (real) |
| `active`/`selected` | gold gradient bg + 3×18 px gold left rail + gold glow (real nav) |
| `disabled` | 40% opacity, `cursor:not-allowed`, no shadow |
| `notifications` | unread = gold dot; severity info/`#3E7BD6`, warning/`#EAB54F`, critical/`#EF4444` |

### 4.5 Contrast (WCAG 2.2 AA)
All text/background pairs must meet **4.5:1** (body) / **3:1** (large ≥18.66 px bold or 24 px). `--dim #B0B8C4` on `--bg #070708` passes; `--muted #7C8798` is reserved for ≥14 px non-essential labels only. Gold `#EAB54F` on ink passes for large text/icons; **gold is not used for body copy**. Every token pair is validated in the §17 checklist.

---

## 5. Typography System

### 5.1 Families (🟡 — unify + self-host)
- **Sans (UI/body):** **Inter** — `["Inter","system-ui","-apple-system","Segoe UI","sans-serif"]`.
- **Mono (numbers/code):** **JetBrains Mono** — `["JetBrains Mono","SFMono-Regular","Menlo","monospace"]`.
- **Target fix (🔴):** the dashboard currently declares Inter/JetBrains but **loads neither** (relies on OS Inter; its mono is Menlo). The system **self-hosts** Inter + JetBrains Mono (woff2, `font-display: swap`, preloaded) in both apps so type is deterministic. §20.

### 5.2 Type scale (🟢 dashboard vars)
| Token | Size | Line-height | Weight | Use |
|---|---|---|---|---|
| `display` | 40 px | 1.1 | 700 | hero numbers, landing headlines |
| `h1` | 32 px | 1.2 | 700 | page titles |
| `h2` | 24 px | 1.25 | 600 | section headers |
| `h3` | 20 px | 1.3 | 600 | card titles |
| `body-lg` | 16 px | 1.5 | 400 | emphasized body |
| `body` | 14 px | 1.5 | 400 | default (base 13 px in dense views) |
| `caption` | 12 px | 1.4 | 500 | labels, metadata |
| `label` | 12 px | 1.3 | 600 | form labels, `letter-spacing 0.02em`, often uppercase eyebrow |
| `button` | 14 px | 1 | 600 | button text |
| `code` / `numbers` / `tables` | 13 px | 1.5 | 500 | **JetBrains Mono + `font-variant-numeric: tabular-nums`** |
| `chart-label` | 11 px | 1 | 500 | axis/legend |

### 5.3 Rules
- **All numeric/tabular data uses mono + `tabular-nums`** so columns align and digits don't jitter on live updates. (Landing has `.tabular`; the dashboard must adopt it app-wide — §20.)
- Letter-spacing: tight on display (`-0.01em`), normal on body, wide on eyebrows/wordmark (`0.02–0.28em`).
- Never more than two weights on a single surface; gold-gradient text reserved for marketing headlines, never data.

---

## 6. Layout System

### 6.1 App shell (🟢)
```
┌───────────────────────────────────────────────┐
│ TopHeader  (60px, blur, z-120, page title 17)  │
├────────────┬──────────────────────────────────┤
│  Sidebar   │  Main (scroll)                     │
│  250px     │    content · max-width per page    │
│  (74 rail) │                                    │
│            ├──────────────────────────────────┤
│            │  TickerBar (bottom)                │
└────────────┴──────────────────────────────────┘
```
- **Grid:** `grid-template-columns: 250px 1fr; height:100vh; overflow:hidden`. Collapsed rail: `74px 1fr`.
- **Sidebar:** brand + grouped nav + account-equity card + market-status pill; active = gold gradient + gold left rail + glow.
- **Grouped-nav IA** (real): `Dashboard` → **Trading** (Strategy Studio, Fleet, Paper Trading, Replay, Backtesting, Optimization Lab, Grid & DCA, Live) → **Performance** (Portfolio, Allocation, Analytics, AI Intelligence) → **Records** (Journal, Decision Archive, Memory) → **System** (Risk, Bot Health, Logs, Settings).
- **TopHeader:** 60 px, `backdrop-filter: blur(6px)`, page title + `HeaderControls` + `NotificationBell`.

### 6.2 Grid & breakpoints (🟡 — desktop-first, target adds mid tiers)
| Tier | Width | Behavior |
|---|---|---|
| Ultrawide | ≥1920 | max content 1680; multi-column dashboards |
| Desktop | 1440–1919 | full shell, 250 px sidebar |
| Laptop | 1280–1439 | full shell, denser cards |
| Small laptop | 1024–1279 | sidebar auto-collapses to 74 px rail (🔴) |
| Tablet | 768–1023 | rail + reflowed 1–2 col (🔴) |
| **Mobile** | ≤720 | off-canvas drawer + scrim (🟢 real single breakpoint) |

**Today** the dashboard has **one** breakpoint (`max-width:720px`); the target adds the intermediate tiers so 1024/1280/1440/1600 are first-class (the brief's required widths). Container: landing `max-w-7xl (80rem)` `px-5 sm:px-8`; sections `py-24 sm:py-32`.

### 6.3 Per-surface layouts
- **Dashboard:** hero + metric cards row + market strip + performance/PnL/health cards (responsive card grid, min 320 px cards).
- **Trading Terminal:** split — chart (fluid) + 330 px decision rail + bottom blotter dock (§9).
- **Analytics:** filter bar + chart-first, tables below.
- **Forms/Settings:** single-column max 640 px, grouped sections, sticky save bar.
- **Tables:** full-width, sticky header, right-aligned mono numbers.
- **Auth:** centered card on `page-depth`, `AuthShell` + showcase panel.
- **Landing:** stacked full-bleed sections, `container-x`.
- **Dialogs:** centered modal (max 560 px) or right drawer (max 480 px).

---

## 7. Component Library

Target: **shadcn/ui + Radix**, themed by the tokens (§14), replacing today's two bespoke sets. Each component below lists the real as-built source so behavior/variants carry over.

### 7.1 Inventory (28 components)
| Component | Variants / states | As-built |
|---|---|---|
| **Button** | primary (gold-sheen), secondary (sky), ghost, outline, danger; sizes sm/md/lg; loading (`Loader2`), disabled, icon | 🟡 landing `ui/Button` + dashboard `.btn`/`ActionButton` |
| **Input / Field** | default, focus (gold ring), error, success, disabled, with-icon, inline-help | 🟡 `ui/Input`,`ui/Field` |
| **Select / Dropdown** | single, searchable, grouped | 🟡 `ui/Select`; Radix `Select`/`DropdownMenu` target |
| **Checkbox / Switch / SegmentedControl / OTPInput** | on/off/indeterminate | 🟢 landing `ui/*` |
| **Card** | default, inset, elevated, interactive, `StatCard` | 🟢 `common/Card`, `ui.tsx StatCard` |
| **Dialog / Modal** | center modal, `ConfirmDialog` | 🟡 `common/Modal`, `ui/ConfirmDialog` → Radix `Dialog` |
| **Drawer** | right/bottom, mobile nav | 🟡 nav drawer → Radix `Dialog`/`Sheet` |
| **Sidebar / Navbar / TopHeader** | expanded/collapsed rail, sticky | 🟢 `layout/*` |
| **Table** | sort, filter, paginate, select, sticky header, expandable, virtual | 🟡 CSS tables → §10 |
| **Tabs / Accordion** | underline tabs, single/multi accordion | 🟡 CSS → Radix `Tabs`/`Accordion` |
| **Charts** | see §8 | 🟢 ECharts + SVG |
| **Timeline** | trade/decision timeline | 🟢 BotTerminal timeline |
| **Toast** | success/danger/warning/info, 2600 ms auto-dismiss | 🟢 `common/Toasts` → Radix `Toast` |
| **Tooltip** | hover/focus, keyboard-reachable | 🔴 → Radix `Tooltip` |
| **Badge / StatusIndicator** | neutral/success/danger/warning/info; pulse-dot live | 🟢 `ui.tsx Badge`, `.pulse-dot` |
| **Avatar** | user/initials | 🔴 |
| **Progress / Loading / Skeleton** | bar, spinner (`Loader2`), skeleton shimmer | 🟢 `ProgressBar`, `ui/Skeleton` |
| **Empty State / Error State** | illustration + action; `ErrorBoundary` fallback | 🟢 `WhyNoTrades`, `OfflineBanner`, `ErrorBoundary` |
| **Pagination** | page/limit; cursor for archives | 🔴 (API §4.5) |
| **Search / Command Palette** | symbol search, global `⌘K` | 🟡 `SymbolSearch` real; palette 🔴 |
| **Code Block** | mono, copy | 🟡 |

### 7.2 Component contract (every component)
States: default · hover · focus-visible · active · disabled · loading · error. Sizes: sm/md/lg where applicable. Every interactive element: keyboard-operable, ARIA-labeled, 2 px gold focus ring, ≥44×44 px hit target on touch. Composed from tokens only — no hard-coded hex/px.

### 7.3 Buttons (canonical spec)
- **Primary:** `bg` gold-sheen, `text` ink `#08080A`, `shadow-gold`, `radius 12px`, `h 40/44px`, weight 600. Hover: brighten + lift 1px. Active: no lift. Focus: gold ring. Loading: `Loader2` spin, label dims, disabled.
- **Secondary:** surface + `border`, text `#FFFFFF`, sky hover tint. **Ghost:** transparent, hover surface. **Danger:** `#EF4444` bg/border. Icon-only: square, `aria-label` required.

---

## 8. Chart Design System

**Engine: Apache ECharts 5.5 (canvas)** for data charts; **hand-rolled SVG** for the Monte-Carlo fan; **reactflow** for the strategy graph. Wrapper: `chart/EChart.tsx` (single init, `ResizeObserver`, dispose-on-unmount).

### 8.1 Candlestick (🟢 `replay/CandleChart.tsx`)
- **Palette:** up `#089981` / down `#F23645`. Right price axis. `animation:false` (perf).
- **Panes (dynamic):** price + volume + oscillator (RSI/MACD/ATR), stacked grids.
- **Overlays:** EMA8 `#22D3EE`, EMA20 `#3B82F6`, EMA30 `#A855F7`, EMA50 `#F59E0B`, VWAP/Supertrend `#EAB54F`, Bollinger `#5B6478`.
- **Zoom:** `dataZoom` inside + slider. **Crosshair:** axis-pointer tooltip (OHLCV + indicators), mono values.

### 8.2 Trade & structure markers (standardized vocabulary)
| Element | Encoding |
|---|---|
| Entry | markPoint ▲/▼ at price, gold |
| Exit | markPoint ✕, neutral |
| SL | markLine dashed `#EF4444` |
| TP (1/2/3) | markLine dashed `#22C55E`, laddered |
| Trade path | line entry→exit, tinted by P&L sign |
| Support / Resistance | markLine solid muted, labeled |
| Demand / Supply zone | markArea green/red @ 8% opacity |
| Order block / FVG | markArea (🟡 — needs OB/FVG detectors, TES §8) |
| Liquidity sweep | markPoint ◇ at wick extreme |
| Grid levels | overlay lines (grid bot) |

### 8.3 Other charts (🟢)
Equity curve (`EquityCurve` → ECharts area), Monte-Carlo fan (`FanChart` — SVG percentile bands p5–p95/p25–p75 + median + bootstrap paths, theme-aware), PnL/allocation doughnuts, sparklines, area/bar, correlation matrix (grid heatmap, diverging palette), trade distribution histogram. **Rule:** all chart color from §4 tokens; axes `#5B6478`, grid `#1C2336`, text `#E6EAF2`, dim `#8A93A6`.

### 8.4 Replay controls & drawing (🟡/🔴)
Play · pause · step-forward · step-back · speed (TES §13) as a fixed control cluster below the chart; crosshair + zoom real; drawing tools (trendline/rect/fib) are target.

---

## 9. Trading Terminal Design (Bot Terminal)

The centerpiece — `pages/BotTerminal.tsx`, the live paper-trading observation lab (streams Binance WS candles). Canonical section map (🟢 real):

| Section | Content |
|---|---|
| **Header strip** | symbol search (any asset), timeframe buttons (1m/3m/5m/15m/1h/4h), strategy selector (8 incl. Decision Brain) |
| **Chart** (left, fluid) | `CandleChart` card; optional Grid Tester + Server-grid 24/7 cards |
| **Decision Panel** (right, 330px) | Bot Decision Engine — live AI reasoning: score, confidence tone (green/gold/red), passed/failed gates, reason |
| **Developer View** | brain state + latest candle (dev mode) |
| **Timeline** | decision/trade timeline events |
| **Blotter dock** (bottom, tabbed) | Open Positions · Trade History · Orders (fills) · Activity (engine log) · Performance · Equity Curve |
| **Status Bar** | live engine/market fields only (`.term-status`) — real data, honest markers when absent |
| **AI Insights / Trade Explanation** | from the ADES layer — market context, entry/risk checklist (PASS/FAIL/**Not checked**), AI commentary, suggestions |

**Design rules:** the decision rail is always visible on desktop; the blotter is collapsible; confidence tone and stage icons are consistent with §4; every number is mono/tabular; nothing shows a value it didn't measure (honesty rule from ADES §11).

---

## 10. Motion Guidelines

Target: **framer-motion** app-wide (today landing-only; dashboard uses CSS transitions). Tokens in §14.

| Motion | Spec | As-built |
|---|---|---|
| Page transition | fade + 8px rise, 200 ms `cubic-bezier(0.22,1,0.36,1)` | 🟡 landing `fade-up` |
| Hover | 120 ms ease-out, ≤2 px lift / +4% bg | 🟢 CSS |
| Button press | 80 ms, scale 0.98 | 🟢 |
| Modal / Drawer | 200 ms fade+scale / slide | 🟡 |
| Sidebar collapse | 180 ms width | 🟢 |
| Chart update | **no animation** on candles (perf); 300 ms on aggregate charts | 🟢 |
| Trade execution | pulse-ring (emerald) on fill | 🟢 `pulse-ring` |
| Notification | slide-in + fade, auto-dismiss 2600 ms | 🟢 |
| Replay tick | crossfade bar advance | 🟡 |
| Loading | shimmer skeleton 2.5 s | 🟢 |

**Reduced motion (WCAG 2.3.3):** `@media (prefers-reduced-motion: reduce)` zeroes durations + `scroll-behavior:auto`. **Real in landing (global block); the dashboard has only one such rule and must adopt the global block (§20).**

---

## 11. UX Patterns

- **Search:** inline symbol search (real) + global **Command Palette (`⌘K`)** (🔴) for navigation/actions/symbols.
- **Filtering:** consistent filter bar (date/strategy/exchange/symbol/status/direction/regime — API §4.5), chips for active filters, "clear all."
- **Navigation:** grouped sidebar + breadcrumb on deep pages + deep links (decisions/trades already deep-linkable).
- **Keyboard shortcuts:** `⌘K` palette, `?` shortcut sheet, `g d`/`g t` go-to, `Esc` closes overlays (real for drawer), arrow-key table nav.
- **Undo:** toast with Undo for reversible actions (delete strategy, reset) (🔴).
- **Confirmation:** `ConfirmDialog` for destructive/irreversible (emergency stop, delete, live-go) — real; typed-confirm for the highest-risk (going live).
- **Bulk actions:** table row selection → action bar (delete/tag/export) (🔴).
- **Optimistic UI** for cheap writes with rollback on error; **loading/empty/error** states mandatory on every data view.

---

## 12. Accessibility Guidelines (WCAG 2.2 AA)

| Requirement | Rule | As-built |
|---|---|---|
| **Never color-only** | numbers sign-prefixed `+`/`−` (U+2212), icons + labels on status | 🟢 `lib/format.ts` |
| **Contrast** | 4.5:1 text / 3:1 large & UI; gold not for body | 🟡 validate all pairs |
| **Keyboard** | every control reachable/operable; `Esc` closes; focus trap in modals | 🟡 (drawer real; modals need trap) |
| **Focus visible** | 2 px gold outline + ring, never removed | 🟢 |
| **Screen reader** | semantic landmarks (`<nav><aside><main>`), `aria-label`, live regions for toasts/price | 🟡 |
| **Reduced motion** | global reduce block | 🟡 (landing only) |
| **Targets** | ≥24×24 CSS px (2.5.8), ≥44 px touch | 🟡 |
| **Forms** | label+input association, error `aria-describedby`, `aria-invalid` | 🟡 |
| **Errors** | route-level `ErrorBoundary` fallback | 🟢 |

**Gate:** no component ships without keyboard operation, a visible focus state, an accessible name, and AA contrast. Automated axe checks + manual keyboard/SR pass in the §18 audit.

---

## 13. Responsive Design Rules

**Desktop-first**, required widths **1920 · 1600 · 1440 · 1280 · 1024 · 768 · mobile**.
- **≥1600:** cap content 1680 px centered; dashboards go 3–4 columns.
- **1280–1599:** full shell; cards 2–3 col.
- **1024–1279:** sidebar → 74 px rail (🔴); cards 2 col; terminal decision-rail stays, blotter collapses.
- **768–1023:** rail; single/two-column reflow; charts full-width; tables horizontal-scroll in a container (never break page layout).
- **≤720 (mobile, 🟢):** off-canvas drawer + scrim; single column; terminal stacks chart → decision → blotter; sticky action bars; tables become cards or horizontal scroll.
**Rule:** every page defines behavior at each tier; wide content (tables/charts) scrolls inside its own `overflow-x:auto` container — the page body never scrolls sideways.

---

## 14. Design Tokens

Single source, emitted to Tailwind config + CSS vars + Figma variables (Style Dictionary). Grounded in the real `src/styles/tradexa-tokens.json` (with the stale purple glow + `theme.ts` legacy hexes fixed — §20).

```jsonc
{
  "color": {
    "bg": "#070708", "bg-2": "#0D0D0F",
    "surface": "#121214", "surface-2": "#0E0E10", "surface-elevated": "#17171A",
    "border": "#232326", "border-soft": "#1A1A1D",
    "text": "#FFFFFF", "dim": "#B0B8C4", "muted": "#7C8798",
    "brand": "#EAB54F", "brand-hover": "#F2C66E", "gold-deep": "#C9A24B",
    "accent": "#3E7BD6", "sky": "#7CB9E8",
    "success": "#22C55E", "danger": "#EF4444", "warning": "#EAB54F", "info": "#3E7BD6",
    "candle-up": "#089981", "candle-down": "#F23645",
    "chart-axis": "#5B6478", "chart-grid": "#1C2336"
  },
  "space": { "1": "8px", "2": "16px", "3": "24px", "4": "32px", "5": "40px" },   // 8-pt
  "radius": { "sm": "12px", "md": "16px", "lg": "20px", "pill": "999px" },
  "shadow": {
    "sm": "0 8px 24px rgba(0,0,0,0.45)",
    "card": "0 20px 50px -24px rgba(0,0,0,0.8)",
    "glow-gold": "0 0 22px rgba(234,181,79,0.28)"          // fixed: was purple
  },
  "font": {
    "sans": "Inter, system-ui, -apple-system, Segoe UI, sans-serif",
    "mono": "JetBrains Mono, SFMono-Regular, Menlo, monospace"
  },
  "type": { "display":"40px","h1":"32px","h2":"24px","h3":"20px","body-lg":"16px","body":"14px","caption":"12px" },
  "motion": {
    "fast":"120ms", "base":"200ms", "slow":"400ms",
    "ease":"cubic-bezier(0.22,1,0.36,1)"
  },
  "opacity": { "disabled":"0.4", "hover-tint":"0.08", "zone":"0.08" },
  "z": { "base":0, "sticky":100, "topbar":120, "drawer":200, "modal":300, "toast":400, "tooltip":500 }
}
```
**Contract:** components read tokens only. Tailwind `theme.extend` maps these names; CSS `:root` mirrors them; Figma variables share the names. One rename, everywhere.

---

## 15. Figma Organization

- **Foundations** — Color (token styles), Typography (text styles), Spacing/Grid, Radius, Shadow, Motion, Iconography (lucide set), Brand (logo/mark).
- **Components** — the §7 library as Figma components with **variants** (variant/size/state) and **Auto Layout**; Radix behaviors annotated.
- **Patterns** — search, filter bar, command palette, confirmation, empty/error/loading, table patterns.
- **Templates** — Dashboard, Trading Terminal, Analytics, Form/Settings, Table, Auth, Landing section, Dialog/Drawer.
- **Pages (Figma file structure):** `00 Cover · 01 Foundations · 02 Components · 03 Patterns · 04 Templates · 05 Flows · 06 Archive`.
- **Variables** — mirror §14 tokens as Figma Variables (modes: Dark default; Light optional collection) so design and code share one token graph. **Dev Mode** annotations link each component to its React source.

---

## 16. React Component Standards

Target stack: **TypeScript + Tailwind + shadcn/ui + Radix + `cva` + `cn()`**. Canonical pattern:

```tsx
// components/ui/button.tsx  (target — replaces dashboard .btn + landing ui/Button)
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";               // clsx + tailwind-merge (already present in landing)

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-[12px] font-semibold " +
  "transition-[transform,background,box-shadow] duration-[120ms] " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/70 " +
  "disabled:opacity-40 disabled:pointer-events-none",
  {
    variants: {
      variant: {
        primary:   "bg-[image:var(--gold-sheen)] text-ink shadow-[var(--shadow-glow-gold)] hover:brightness-105 active:translate-y-0",
        secondary: "bg-surface border border-border text-text hover:bg-white/[0.04]",
        ghost:     "bg-transparent hover:bg-white/[0.04]",
        danger:    "bg-danger/90 text-white hover:bg-danger",
      },
      size: { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4 text-sm", lg: "h-11 px-5 text-sm" },
    },
    defaultVariants: { variant: "primary", size: "md" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  asChild?: boolean; loading?: boolean;
}

export function Button({ className, variant, size, asChild, loading, children, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp className={cn(button({ variant, size }), className)} aria-busy={loading} {...props}>
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </Comp>
  );
}
```

**Rules:** every component (1) is typed, props documented; (2) reads tokens, never literals; (3) forwards `className` + `ref`, supports `asChild` where composable; (4) is accessible by default (Radix primitive underneath for overlays/menus/tooltips); (5) works in dark (and light when added) via tokens; (6) has a Storybook story per variant/state; (7) ships with the §17 checklist passing. `cn()` (clsx + tailwind-merge) is the class merger (already in the landing).

---

## 17. UI Quality Checklist (gate every page)

- [ ] **Color:** only tokens; no raw hex/rgb; every text/bg pair ≥ AA; gold not used for body.
- [ ] **Spacing:** all margins/paddings on the 8-pt scale; consistent card/section rhythm.
- [ ] **Typography:** type scale only; numbers mono + tabular-nums; ≤2 weights per surface.
- [ ] **Components:** built from the library; no one-off buttons/inputs; all states styled.
- [ ] **Radius/shadow/border:** tokens only; consistent elevation.
- [ ] **Icons:** lucide, one version, `strokeWidth 1.9`, sized by scale.
- [ ] **Charts:** token palette; candle vs P&L colors correct; axes/grid tokens; tabular tooltips.
- [ ] **States:** loading, empty, and error states present for every data view.
- [ ] **Responsive:** correct at 1920/1600/1440/1280/1024/768/mobile; no horizontal body scroll.
- [ ] **Motion:** durations from tokens; reduced-motion respected.
- [ ] **Dark:** renders correctly on dark surfaces; no light-mode assumptions leaking.
- [ ] **Perf:** virtualized long tables; `animation:false` on candles; no layout thrash on live update.

## 18. UX Audit Checklist (per page)

- [ ] **Visual consistency** with sibling pages (header, spacing, card style).
- [ ] **Interaction quality:** hover/focus/active/disabled all feel right; ≤16 ms response.
- [ ] **Accessibility:** full keyboard pass; visible focus throughout; SR landmarks + names; axe clean; targets ≥24 px.
- [ ] **Navigation:** clear location, breadcrumbs on deep pages, working deep links.
- [ ] **Feedback:** every action confirms (toast/inline); destructive actions confirm first; errors are actionable.
- [ ] **Content:** honest empty/error copy; no fabricated data; "Not checked"/"not captured" where truthful.
- [ ] **Performance:** fast first paint, virtualized data, cached polls (`useLive`), no jank on stream.
- [ ] **Responsive behavior** verified at every tier.

---

## 19. UI/UX Design System Readiness Score

| Dimension | Score | Notes |
|---|---:|---|
| **Brand identity** | 8/10 | Strong N-monogram, gold+signal-blue, dark-luxury — premium and distinctive. |
| **Color system** | 7/10 | Rich semantic + trading palette; two-golds + stale-purple divergence to resolve. |
| **Typography** | 5/10 | Good scale; dashboard doesn't load its fonts; tabular-nums not app-wide. |
| **Spacing/layout** | 7/10 | Real 8-pt scale + coherent shell + grouped IA; only one dashboard breakpoint. |
| **Component library** | 4/10 | Two bespoke sets, no shared library, no shadcn/Radix — the core gap. |
| **Chart system** | 8/10 | Professional ECharts terminal, rich overlays/markers — genuinely strong. |
| **Trading terminal** | 8/10 | Dense, live, well-sectioned observation lab. |
| **Motion** | 5/10 | Nice on landing (framer-motion); minimal + inconsistent on the app. |
| **Accessibility** | 6/10 | Real wins (sign prefixes, focus rings, ErrorBoundary); gaps in SR/keyboard/reduced-motion on the app. |
| **Responsive** | 5/10 | Solid mobile drawer; missing 1024–1600 tiers. |
| **Design tokens** | 6/10 | Real token JSON + CSS vars + ECharts theme, but three token sources with stale values. |
| **Consistency across apps** | 3/10 | Two styling engines, two component sets, two golds — the headline debt. |

### **Overall: 6.5 / 10** — *"A premium, coherent identity implemented as two separate front-ends; the work is unification, not reinvention."*

The brand, the chart terminal, and the density are already institutional-grade (8s). The score is held back by exactly the thing this document exists to fix: **there is no single design system** — the app is hand-CSS + ECharts, the landing is Tailwind + framer-motion, neither uses shadcn/Radix, and tokens have drifted (two golds, stale purple, unloaded fonts). §20 is the convergence path; executing it lifts this to **9/10**, at which point a new page is provably indistinguishable from the rest of the product.

---

## 20. Convergence plan (as-built → one design system)

Non-breaking, incremental — the visual analog of the TES's shared-core plan.

1. **Publish the token package** (§14) as the single source; generate Tailwind config + CSS vars + Figma variables from it. Fix the three real drifts: **rename `--purple`→`--gold`**, correct `tradexa-tokens.json` glow (purple→gold), and fix `theme.ts` stale `bg/card`.
2. **Resolve the two golds:** `#EAB54F` = canonical brand; `#C9A24B` = `gold-deep` for large fills. One value in components.
3. **Self-host Inter + JetBrains Mono** in both apps; apply `tabular-nums` to all numeric/table text app-wide.
4. **Adopt Tailwind in the dashboard** (or emit the tokens as Tailwind + keep the CSS layer as a thin compat shim), so both apps share utility semantics.
5. **Introduce the shadcn/ui + Radix component library** (§16), themed by the tokens; migrate bespoke components one family at a time (Button → Input → Dialog → Table …), keeping the CSS classes as aliases during migration.
6. **Unify motion** on framer-motion with the motion tokens + the global reduced-motion block in the dashboard.
7. **Add the intermediate breakpoints** (1024/1280/1440/1600) and the collapse/reflow rules.
8. **Ship the Storybook + Figma library**; gate new pages on the §17/§18 checklists in CI (visual-regression + axe).

Each step is shippable and reversible; after step 5 a page built from the library is indistinguishable across apps — the definition of done.

---

*End of UI/UX Design System Specification v1.0. Implement in the order of §20; gate every page on §17 (UI) + §18 (UX). Consistent with the ADES (confidence tones, honesty markers), TES §9/§13 (terminal, replay controls), and API §4.5 (filter/sort/paginate). This completes the nine-part blueprint set: PRD · Audit · TRD · SAD · DDS · API · TES · ADES · UDS.*
