# TradeLogX Nexus — Enterprise UI/UX Design System (Version 1.0)

*The single source of truth for every screen, component, token, interaction, and rule. This is the **canonical** design system; it supersedes and extends `docs/UDS.md` to full enterprise depth (23 sections). Maintains the existing TradeLogX Nexus branding; improves consistency, scalability, accessibility, and DX.*

> **Version 1.0 · 2026-07-22 · Dark-first · Institutional · React + TypeScript + Tailwind + shadcn/ui + Radix**

---

## Reading guide — grounded, and honest about convergence

Values here are **real** — pulled from the codebase, not invented (verified in the UDS inventory). Tags: 🟢 **EXISTS** · 🟡 **PARTIAL / diverges across the two front-ends** · 🔴 **NEW/TARGET**.

**The one architectural truth this system resolves:** the app (`automation-hub-dashboard`) is hand-written **CSS-variables + Apache ECharts, no Tailwind**; the landing (`tradexa-landing`) is **Tailwind + framer-motion**; **neither uses shadcn/ui or Radix** today. This document defines **one** token set + **one** component library (Tailwind + shadcn/Radix) that both adopt — plus the migration (§ Developer Checklist / UDS §20). Five real inconsistencies it fixes: two golds (`#EAB54F` vs `#C9A24B`), dashboard fonts declared-but-not-loaded, the `--purple` variable that is actually gold, stale token values (purple glow, legacy `theme.ts`), and candle colors intentionally distinct from P&L.

---

## 1. Executive Summary

TradeLogX Nexus must feel like an institutional trading platform — **premium, minimal, dark-first, data-dense, fast, AI-powered** — in the lineage of TradingView, Bloomberg, Coinbase Advanced, Binance Futures, Stripe, Linear, Vercel, Raycast, Arc, and Notion. This system delivers that consistently through five layers:

1. **Tokens** — one graph of color/type/spacing/radius/shadow/elevation/motion/z-index (§16), emitted to Tailwind, CSS variables, and Figma variables. Every value below traces to a token.
2. **Components** — a Tailwind + shadcn/Radix library (§9), accessible by default, themed by tokens, replacing today's two bespoke sets.
3. **Charts** — one ECharts language for candles, indicators, structure, and trade markers (§10).
4. **Rules** — WCAG 2.2 AA (§14), desktop-first responsive from 480→2560 (§15), subtle performant motion (§13).
5. **Governance** — UI/UX audits (§19–20) + consistency and implementation checklists (§21–22) that gate every new page.

**Acceptance test:** a new page built from these tokens + components is *visually identical* to the rest of the app, passes §21/§22, and meets WCAG 2.2 AA — with no bespoke CSS. **Readiness today: 6.5/10** (§23) — a premium identity implemented as two front-ends; the work is convergence, not redesign.

---

## 2. Design Philosophy

| Principle | Meaning | Applied |
|---|---|---|
| **Simplicity** | Remove until only signal remains. | Chrome recedes; data leads. |
| **Information hierarchy** | The most decision-relevant number is the most prominent. | Display type for equity/PnL; muted for metadata. |
| **Readability** | Numbers never jitter; text always contrasts. | Mono + `tabular-nums`; AA contrast. |
| **Speed** | Perceived performance is design. | ≤16 ms interactions; `animation:false` on candles; virtualized tables. |
| **Consistency** | One action, one look, everywhere. | One component library; no one-offs. |
| **Accessibility** | Usable by everyone, by keyboard, by SR. | WCAG 2.2 AA is a gate, not a nice-to-have. |
| **Predictability** | The UI does what a trader expects. | Standard patterns (Esc closes, ⌘K search, sign-prefixed numbers). |
| **Scalability** | New surfaces cost little; drift can't accumulate. | Tokens + composition. |
| **User confidence** | Trust through honesty. | Never fake data; `"Not checked"` markers; real-data-only charts. |
| **Minimal cognitive load** | Summary first, detail on demand. | Progressive disclosure, drill-downs, the Observation Terminal. |

---

## 3. Brand Guidelines

- **Wordmark:** "TradeLogX" (Inter, 15px, bold) + "Nexus" (`tracking-[0.28em]`, gold @ 80%). **Mark:** the two-tone N-monogram (silver ascent `#E9EEF3→#AEB7C2`, gold descent `#E7C766→#C6961F`) in a gold/steel ring — an up/down market move. Source `public/nexus-mark.svg`; viewBox `0 0 96 96`.
- **Logo spacing:** clear space = 0.5× mark height. **Sizes:** favicon 16/32/48; apple-touch 180; nav rail 20–24; header lockup 28–32; auth/marketing 48+. **Min** 20px.
- **Usage:** `LogoMark` alone in the collapsed rail + favicons; full lockup expanded/auth/marketing. **Never** recolor, add effects beyond the shipped gradient, stretch, or place on busy imagery without the ink scrim.
- **Brand gradients:** `gold-sheen` `linear-gradient(135deg,#E7D89A,#C8A94B,#A98E3A)` (headlines/primary CTA); `page-depth` `radial-gradient(120% 85% at 50% 0%,#0D0C0A,#08080A,#050506)`; `radial-fade` gold glow.
- **Illustrations / empty states:** data-as-art (charts, animated brain/engine visuals). Empty states = a lucide glyph + one honest line + a primary action (e.g. `WhyNoTrades`). **No mascots, no stock photography.**
- **Marketing assets:** gold-gradient headlines, glass cards, restrained motion. **App icons/favicon:** shipped set in both `public/` — keep identical across apps; `theme-color` `#0a0a0c`.
- **Consolidation (🔴):** one shared `Logo`/`LogoMark` + brand-asset package consumed by both apps (today duplicated).

---

## 4. Color System

Dark-first, with a **light collection** defined (brief requirement) even though dark is default. Canonical values reconcile the two golds (app `#EAB54F` = brand; landing `#C9A24B` = `gold-deep`).

### 4.1 Semantic tokens — dark (default) / light
| Token | Dark | Light | Role |
|---|---|---|---|
| `bg` | `#070708` | `#F7F8FA` | app canvas |
| `bg-2` | `#0D0D0F` | `#EEF0F4` | raised canvas |
| `surface` / `card` | `#121214` | `#FFFFFF` | card |
| `panel` | `#0E0E10` | `#F4F5F8` | inset panel (terminal rails) |
| `sidebar` | `#0A0A0C` | `#FFFFFF` | nav column |
| `navigation` | `#0A0A0C` | `#FFFFFF` | top bar |
| `surface-elevated` | `#17171A` | `#FFFFFF` | modal/popover |
| `border` | `#232326` | `#E3E6EC` | default border |
| `divider` | `#1A1A1D` | `#EDEFF3` | hairline |
| `text` | `#FFFFFF` | `#0B0B0D` | primary text |
| `dim` | `#B0B8C4` | `#3C4552` | secondary text |
| `muted` | `#7C8798` | `#6B7480` | tertiary (≥14px only) |
| `primary` / `brand` | `#EAB54F` | `#B4832A` | brand, primary action, active nav |
| `gold-deep` | `#C9A24B` | `#8A7233` | large fills / marketing |
| `secondary` | `#7CB9E8` | `#2F6FB0` | secondary action, links |
| `accent` / `ai` | `#3E7BD6` | `#2C63B8` | AI/data highlight |
| `success` / `profit` / `bullish` / `positive-pnl` | `#22C55E` | `#15803D` | wins, up |
| `danger` / `loss` / `bearish` / `negative-pnl` | `#EF4444` | `#B91C1C` | losses, down |
| `warning` / `risk` | `#EAB54F` | `#B4832A` | caution |
| `info` | `#3E7BD6` | `#2C63B8` | neutral info |
| `replay` | `#A855F7` | `#7C3AED` | replay-mode accent/cursor |
| `analytics` | `#22D3EE` | `#0E7490` | analytics accent |
| `bot` | `#EAB54F` | `#B4832A` | bot/engine accent |

### 4.2 Chart tokens
| Token | Value | Role |
|---|---|---|
| `candle-up` | `#089981` | up candle *(intentionally ≠ profit green)* |
| `candle-down` | `#F23645` | down candle *(intentionally ≠ loss red)* |
| `chart-bg` | `transparent` (inherits `bg`) | plot area |
| `chart-grid` | `#1C2336` | gridlines |
| `chart-axis` | `#5B6478` | axis text/line |
| `chart-tooltip-bg` | `#17171A` | crosshair tooltip surface |
| `chart-hover` | `rgba(234,181,79,0.10)` | hovered element tint |
| `ema8/20/30/50` | `#22D3EE / #3B82F6 / #A855F7 / #F59E0B` | overlays |
| `vwap` / `supertrend` | `#EAB54F` | gold overlays |
| `bollinger` | `#5B6478` | band |
| Heatmap | `#EF4444 → #7C8798 → #22C55E` | diverging (correlation/exposure) |

### 4.3 Interaction-state tokens
| State | Treatment |
|---|---|
| `hover` | +4% surface lightness; nav hover `rgba(124,185,232,0.08)` |
| `focus` | 2px `rgba(234,181,79,0.55)` outline + 3px `rgba(234,181,79,0.12)` ring |
| `active`/`selected` | gold-gradient bg + 3×18px gold left rail + gold glow |
| `pressed` | scale 0.98 + −4% lightness |
| `disabled` | 40% opacity, `not-allowed`, no shadow |

### 4.4 Contrast rule (AA)
Text/bg ≥ **4.5:1** (body) / **3:1** (large ≥18.66px bold / 24px). Gold is **never** body copy; `muted` only for ≥14px non-essential labels. Every pair validated in §21.

---

## 5. Typography System

- **Primary:** **Inter** (`Inter, system-ui, -apple-system, Segoe UI, sans-serif`). **Monospace:** **JetBrains Mono** (`JetBrains Mono, SFMono-Regular, Menlo, monospace`). 🔴 **Self-host both** (woff2, `font-display:swap`, preload); the dashboard currently declares but doesn't load them.

| Style | Size | LH | Weight | LS | Use |
|---|---|---|---|---|---|
| Display | 40px | 1.1 | 700 | −0.01em | hero equity/PnL, marketing |
| H1 | 32px | 1.2 | 700 | −0.01em | page title |
| H2 | 24px | 1.25 | 600 | 0 | section |
| H3 | 20px | 1.3 | 600 | 0 | card title |
| H4 | 17px | 1.35 | 600 | 0 | sub-section / topbar title |
| H5 | 15px | 1.4 | 600 | 0.01em | dense group label |
| Body Large | 16px | 1.5 | 400 | 0 | emphasized body |
| Body | 14px | 1.5 | 400 | 0 | default (13px in dense views) |
| Small | 13px | 1.5 | 400 | 0 | secondary body |
| Caption | 12px | 1.4 | 500 | 0.01em | metadata |
| Label | 12px | 1.3 | 600 | 0.02em | form labels / eyebrows (often uppercase) |
| Button | 14px | 1 | 600 | 0.01em | button text |
| Table | 13px | 1.5 | 500 | 0 | **mono + tabular-nums** |
| Trading Numbers | 13–40px | — | 500–700 | 0 | **mono + tabular-nums**, sign-prefixed |
| Chart Labels | 11px | 1 | 500 | 0 | axis/legend |
| Code | 13px | 1.5 | 500 | 0 | mono |

**Rules:** all numeric/tabular data → **mono + `tabular-nums`** (columns align, digits don't jitter live). ≤2 weights per surface. Gold-gradient text only for marketing headlines, never data. **Responsive scale:** at ≤768px drop Display→32, H1→28, H2→20; at ≥1920 allow Display→48 on marketing only.

---

## 6. Spacing System (8-point)

Token scale (px), `--space-*`:
`4 (0.5) · 8 (1) · 12 (1.5) · 16 (2) · 20 (2.5) · 24 (3) · 32 (4) · 40 (5) · 48 (6) · 56 (7) · 64 (8) · 80 (10) · 96 (12)`

| Token | Use |
|---|---|
| 4 | icon↔label gap, chip padding-y |
| 8 | tight control padding, inline gaps |
| 12 | input padding-x, small card padding |
| 16 | **default** card padding, stack gap |
| 20 | comfortable card padding |
| 24 | card→card gap, group spacing |
| 32 | section padding, panel gutter |
| 40 | between major blocks |
| 48 | page top padding, section rhythm |
| 56–64 | large section spacing (analytics/landing) |
| 80–96 | landing section rhythm (`py-24/py-32`) |

**Rule:** every margin/padding is a token; no arbitrary px. Card default padding = 16–20; page gutter = 24–32.

---

## 7. Grid System

| Breakpoint | Range | Container max | Sidebar | Panel (terminal rail) | Behavior |
|---|---|---|---|---|---|
| **2560 (Ultrawide)** | ≥2160 | 1920 | 250 | 360 | center content; 4-col dashboards; wider chart |
| **1920 (Large desktop)** | 1680–2159 | 1680 | 250 | 360 | full shell, 3–4 col |
| **1600** | 1536–1679 | 1536 | 250 | 340 | full shell, 3 col |
| **1440 (Desktop)** | 1440–1535 | 1360 | 250 | 330 | full shell, 3 col |
| **1280 (Laptop)** | 1280–1439 | 1200 | 250 | 330 | denser cards, 2–3 col |
| **1024 (Small laptop)** | 1024–1279 | 100% | **74 rail** 🔴 | 300 | rail auto-collapse; 2 col; blotter collapses |
| **768 (Tablet)** | 768–1023 | 100% | 74 rail | full-width | 1–2 col; charts full-width; tables scroll |
| **480 (Mobile-L)** | 480–767 | 100% | drawer | stacked | off-canvas drawer; single col |
| **<480 (Mobile-S)** | <480 | 100% | drawer | stacked | compact; sticky action bars |

**Widths:** content max **1680**; sidebar **250px** (74 collapsed); terminal decision rail **330px** (300–360 responsive); form column max **640px**; modal max **560px**; drawer max **480px**. **Safe spacing:** min 16px page gutter mobile, 24–32 desktop. Today the dashboard has **one** real breakpoint (720px, 🟡) — the intermediate tiers are 🔴.

---

## 8. Layout Guidelines

**App shell (🟢):** `TopHeader (60px, blur, z-topbar)` + `Sidebar (250px)` + scrollable `Main` + bottom `TickerBar`. Active nav = gold gradient + gold left rail + glow. Grouped IA: `Dashboard` → Trading → Performance → Records → System.

| Surface | Layout |
|---|---|
| **Dashboard** | hero + metric-card row + market strip + performance/PnL/health cards (min 320px card grid) |
| **Trading Terminal** | chart (fluid) + 330px decision rail + collapsible bottom blotter dock (§11) |
| **Paper Trading** | = Terminal (the terminal *is* the paper page) + account switcher |
| **Replay** | chart + replay controls cluster + timeline; replay-accent cursor |
| **Backtesting** | config bar + chart-first + metrics cards + equity/MC charts + trade table |
| **Analytics** | filter bar + chart-first + tables below; explicit offline state |
| **Portfolio** | allocation + exposure heatmap + performance history |
| **Strategy Studio** | builder canvas (reactflow) + block palette + preview chart + library |
| **AI Intelligence** | market-context cards + confidence + recommendations (honest gating) |
| **Settings** | single-column ≤640px, grouped sections, sticky save bar, honest LOCKED rows |
| **Authentication** | centered card on `page-depth` + showcase panel |
| **Landing** | stacked full-bleed sections, `container-x` (max-w-7xl), `py-24/32` |
| **Dialogs/Modals** | centered ≤560px, scrim, focus-trap |
| **Drawers** | right/bottom ≤480px, slide, scrim |

---

## 9. Component Library

Target **shadcn/ui + Radix**, themed by tokens. Every component documents: **Purpose · Variants · Sizes · States · Accessibility · Usage · Interaction**. States baseline: default · hover · focus-visible · active/pressed · disabled · loading · error. Sizes sm/md/lg where applicable. Min hit-target 44×44 touch / 24×24 pointer.

| Component | Variants | Radix/base | As-built |
|---|---|---|---|
| **Button** | primary(gold-sheen)/secondary/ghost/outline/danger | button/Slot | 🟡 |
| **Icon Button** | ghost/solid/danger; sm/md/lg square | button | 🟡 |
| **Split Button** | action + dropdown chevron | DropdownMenu | 🔴 |
| **Input / Textarea** | default/error/success/with-icon; char-limit | — | 🟡 |
| **Select** | single/grouped | Select | 🟡 |
| **Combobox** | searchable, async, multi | Popover+Command | 🔴 |
| **Dropdown** | menu, nested, checkbox items | DropdownMenu | 🟡 |
| **Checkbox / Radio / Switch** | + indeterminate | Checkbox/RadioGroup/Switch | 🟢 (landing) |
| **Slider** | single/range; risk% inputs | Slider | 🔴 |
| **Search** | inline + global (⌘K) | Command | 🟡 (symbol search real) |
| **Date Picker** | single/range (backtest windows) | Popover+calendar | 🔴 |
| **Tables** | see §12 | — | 🟡 |
| **Cards** | default/inset/elevated/interactive/StatCard | — | 🟢 |
| **Charts** | see §10 | ECharts | 🟢 |
| **Timeline** | trade/decision events | — | 🟢 |
| **Toast** | success/danger/warning/info, 2600ms | Toast | 🟢 |
| **Tooltip** | hover/focus, keyboard-reachable | Tooltip | 🔴 |
| **Popover** | menus, filter panels | Popover | 🔴 |
| **Badge / Status Indicator** | neutral/success/danger/warning/info; live pulse-dot | — | 🟢 |
| **Avatar** | user/initials | Avatar | 🔴 |
| **Progress / Loading / Skeleton** | bar/spinner/shimmer | Progress | 🟢 |
| **Tabs / Accordion** | underline tabs; single/multi | Tabs/Accordion | 🟡 |
| **Alert / Banner** | info/success/warning/danger; dismissible | — | 🟡 (OfflineBanner) |
| **Notification** | list item + unread dot | — | 🟢 |
| **Dialog / Drawer** | modal/confirm; right/bottom | Dialog | 🟡 |
| **Pagination** | page + cursor | — | 🔴 |
| **Command Palette** | ⌘K nav/actions/symbols | Command+Dialog | 🔴 |
| **Empty / Error State** | glyph + line + action; ErrorBoundary fallback | — | 🟢 |

**Canonical Button:** primary = `bg` gold-sheen, `text` ink `#08080A`, `shadow-gold`, radius 12px, h 40/44, weight 600; hover brighten+lift 1px; pressed scale 0.98; focus gold ring; loading = `Loader2` spin + disabled.

---

## 10. Chart Design System

**Engine: ECharts 5.5** (canvas) via `chart/EChart.tsx` (single-init, ResizeObserver, dispose). Candles in `replay/CandleChart.tsx`.

**Candlestick:** up `#089981` / down `#F23645`; right price axis; dynamic panes (price + volume + oscillator); `animation:false`. **Overlays:** EMA8 `#22D3EE`, EMA20 `#3B82F6`, EMA30 `#A855F7`, EMA50 `#F59E0B`, VWAP/Supertrend `#EAB54F`, Bollinger `#5B6478`.

**Structure & trade vocabulary (standardized):**
| Element | Encoding |
|---|---|
| Volume | sub-pane bars, up/down tinted |
| SMA/EMA/VWAP | overlay lines (colors above) |
| Order Blocks | markArea, muted fill @8%, labeled |
| Supply/Demand | markArea red/green @8% |
| Liquidity (sweep) | markPoint ◇ at wick extreme |
| BOS / CHoCH | markLine + label (structure flip) |
| Fair Value Gap | markArea between imbalance candles |
| Trend lines | solid overlay |
| Risk lines | dashed |
| Entry | markPoint ▲/▼ gold |
| Exit | markPoint ✕ neutral |
| Stop Loss | markLine dashed `#EF4444` |
| Take Profit | markLine dashed `#22C55E` |
| Trailing Stop | markLine dotted `#F59E0B`, moves with price |
| Partial TP | markLine dashed `#22C55E` @ TP1/2/3, labeled fraction |
| Trade Path | line entry→exit tinted by P&L sign |
| Replay Cursor | vertical line `#A855F7` (replay accent) |
| Crosshair | axis-pointer, mono tooltip (OHLCV+indicators) |
| Zoom | dataZoom inside + slider |
| Drawing Tools | trendline/rect/fib (🔴) |
| Tooltip | `chart-tooltip-bg` surface, tabular values |
| Context Menu | right-click: add indicator, measure, snapshot (🔴) |
| Developer Overlay | brain-state/latest-candle debug pane (🟢 dev mode) |

**Rule:** every mark maps to a **real computed value** — never decorative (the honesty rule; strategy drives `meta.viz`). **Accessible charts:** provide a data-table fallback + `aria-label` summary per chart (§14).

---

## 11. Bot Observation Terminal (flagship) — design guidelines

`pages/BotTerminal.tsx`. Per-section spacing/sizing/responsive:

| Section | Spec | Responsive |
|---|---|---|
| **Header** | 56–60px; symbol search + timeframe segmented (1m/3m/5m/15m/1h/4h) + strategy select; 16px gaps | ≤768 wraps to 2 rows |
| **Chart** | fluid width, min-height 420px; card padding 12; `animation:false` | full-width < 1024 |
| **Decision Engine Panel** | 330px right rail (300–360); score + confidence tone (green/gold/red) + passed/failed gates + reason; 16px section gaps | moves below chart < 1024 |
| **AI Explanation Panel** | within rail; market context + entry/risk checklist (PASS/FAIL/**Not checked**) + commentary | collapsible |
| **Order Details / Position Info / Risk Info** | rail cards; mono/tabular; sign-prefixed P&L | stack |
| **Trade Timeline** | vertical events, 8px node gap, time on left | — |
| **Trade History / Blotter dock** | bottom tabs (Positions·History·Orders·Activity·Performance·Equity); virtualized rows | collapses to a sheet on mobile |
| **Replay Controls** | play·pause·step-back·step-forward·speed cluster below chart; replay-accent | icon-only < 768 |
| **Developer Mode** | brain state + latest candle; monospace | hidden < 1024 by default |
| **Performance Summary** | live track record card (win rate, PF, expectancy) | — |
| **Status Bar** | `.term-status`, real engine/market fields only, honest markers when absent | single line, scroll |

**Rules:** decision rail always visible ≥1024; every number mono/tabular; nothing renders a value it didn't measure.

---

## 12. Table Design System

| Feature | Standard |
|---|---|
| Sorting | header click → `sort=-field`; arrow indicator; mono right-aligned numbers |
| Filtering | filter bar above; active chips; "clear all" |
| Pagination | page + limit; **cursor** for archives (decisions/trades) |
| Sticky headers | always on scroll; `z-sticky` |
| Expandable rows | chevron → detail row (decision drill-down) |
| Selection | checkbox col → action bar |
| Bulk actions | appear on selection (delete/tag/export) 🔴 |
| Virtual scrolling | for blotter/logs/decisions (>100 rows) 🔴 |
| Resizable columns | drag handles 🔴 |
| Column visibility | menu toggle 🔴 |

Row height 40 (compact 32); zebra off (use dividers); numbers `tabular-nums`; P&L colored **and** sign-prefixed.

---

## 13. Motion Design

Target framer-motion app-wide (today landing-only). Subtle + performant.

| Motion | Spec |
|---|---|
| Page transition | fade + 8px rise, 200ms `cubic-bezier(0.22,1,0.36,1)` |
| Hover | 120ms ease-out, ≤2px lift / +4% bg |
| Button | press scale 0.98, 80ms |
| Sidebar collapse | width 180ms |
| Chart updates | **none** on candles; 300ms on aggregate charts |
| Replay animation | crossfade bar advance; cursor slide |
| Trade execution | emerald `pulse-ring` on fill |
| Toast | slide-in + fade; auto-dismiss 2600ms |
| Loading | shimmer skeleton 2.5s |
| Dialog | fade+scale 200ms |
| Accordion / Expansion | height 180ms ease |

**Reduced motion:** global `@media (prefers-reduced-motion: reduce)` zeroes durations + `scroll-behavior:auto` (🟡 real on landing; dashboard adopts).

---

## 14. Accessibility Standards (WCAG 2.2 AA)

| Requirement | Rule | State |
|---|---|---|
| Never color-only | sign-prefixed `+`/`−` (U+2212) numbers | 🟢 |
| Focus visible | 2px gold outline + ring, never removed | 🟢 |
| Keyboard nav | all controls operable; Esc closes; focus-trap in modals | 🟡 |
| ARIA labels | landmarks (`nav/aside/main`), names on icon buttons, `aria-invalid`/`describedby` on fields | 🟡 |
| Contrast | 4.5:1 / 3:1; gold not body | 🟡 validate |
| Reduced motion | global block | 🟡 |
| Screen reader | live regions for streaming price/toasts | 🔴 |
| Accessible charts | data-table fallback + summary `aria-label` per chart | 🔴 |
| Targets | ≥24×24 pointer / ≥44 touch | 🟡 |

**Gate:** no component ships without keyboard operation, visible focus, an accessible name, and AA contrast. CI: axe + manual keyboard/SR pass.

---

## 15. Responsive Design Rules

Desktop-first; behavior per breakpoint (§7 table). Per-component: Buttons keep 44px touch height ≤768; Tables → horizontal scroll in `overflow-x:auto` (never break body); Sidebar → rail ≤1024 → drawer ≤767; Terminal → chart/rail/blotter **stack** ≤1024; Cards → 4→3→2→1 col across tiers; Modals → full-height sheet ≤480; Charts → full-width ≤1024, reduced pane count ≤768. **Rule:** the page body never scrolls horizontally; wide content scrolls inside its own container. Every page documents behavior at 2560/1920/1600/1440/1280/1024/768/480.

---

## 16. Design Tokens

One source → Tailwind config + CSS vars + Figma variables (Style Dictionary). Colors in §4; here the rest.

```jsonc
{
  "radius":   { "xs":"8px","sm":"12px","md":"16px","lg":"20px","xl":"28px","pill":"999px" },
  "border":   { "hairline":"1px","default":"1px","strong":"2px" },
  "shadow":   {
    "sm":"0 8px 24px rgba(0,0,0,0.45)",
    "card":"0 20px 50px -24px rgba(0,0,0,0.8)",
    "glass":"0 1px 0 0 rgba(255,255,255,0.05) inset, 0 24px 60px -20px rgba(0,0,0,0.7)",
    "glow-gold":"0 0 22px rgba(234,181,79,0.28)"          // fixed: was purple
  },
  "elevation":{ "0":"none","1":"shadow.sm","2":"shadow.card","3":"shadow.glass","overlay":"shadow.card" },
  "opacity":  { "disabled":"0.4","hover-tint":"0.08","zone":"0.08","scrim":"0.6" },
  "motion":   { "fast":"120ms","base":"200ms","slow":"400ms","ease":"cubic-bezier(0.22,1,0.36,1)","spring":"cubic-bezier(0.34,1.56,0.64,1)" },
  "z":        { "base":0,"sticky":100,"topbar":120,"drawer":200,"modal":300,"popover":350,"toast":400,"tooltip":500 },
  "space":    { "1":"4px","2":"8px","3":"12px","4":"16px","5":"20px","6":"24px","8":"32px","10":"40px","12":"48px","14":"56px","16":"64px","20":"80px","24":"96px" },
  "font":     { "sans":"Inter, system-ui, -apple-system, Segoe UI, sans-serif","mono":"JetBrains Mono, SFMono-Regular, Menlo, monospace" }
}
```
**Contract:** components read tokens only. One rename propagates to Tailwind, CSS, and Figma.

---

## 17. Figma Organization

- **Foundations** — Color (dark+light styles), Typography (text styles), Spacing/Grid, Radius, Shadow/Elevation, Motion, Iconography (lucide), Brand.
- **Tokens** — as **Figma Variables** mirroring §16, with **modes: Dark (default) + Light**; token names identical to code.
- **Components** — the §9 library with **Variants** (variant/size/state) + **Auto Layout**; Radix behavior annotated; Dev-Mode links to the React source.
- **Patterns** — search, filter bar, command palette, confirmation, empty/error/loading, table patterns, terminal rail.
- **Templates** — Dashboard, Terminal, Analytics, Form/Settings, Table, Auth, Landing, Dialog/Drawer.
- **Pages:** `00 Cover · 01 Foundations · 02 Tokens · 03 Components · 04 Patterns · 05 Templates · 06 Flows · 07 Archive`.

---

## 18. React Component Standards

Stack: **TypeScript + Tailwind + shadcn/ui + Radix + `cva` + `cn()`** (clsx+tailwind-merge, already in the landing). Rules: (1) typed, documented props; (2) tokens only — no literal hex/px; (3) forward `className`+`ref`, support `asChild` for composables; (4) accessible by default (Radix primitive under overlays/menus/tooltips); (5) dark+light via tokens; (6) a Storybook story per variant/state; (7) passes §21/§22. Canonical example (Button with `cva` + Radix `Slot` + gold-sheen primary + focus ring + loading) — see UDS §16 for the full snippet, reused verbatim.

---

## 19. UI Audit Report (per-page, grounded)

Scale: ✅ good · 🟡 minor · 🔴 fix.

| Page | Consistency | Hierarchy | Spacing | Typography | Responsive | Reuse | Notes |
|---|---|---|---|---|---|---|---|
| Dashboard/Overview | ✅ | ✅ | ✅ | 🟡 | 🟡 | 🟡 | fonts not loaded; card reuse good |
| Bot Terminal | ✅ | ✅ | ✅ | 🟡 | 🟡 | 🟡 | dense, strong; rail reflow ≤1024 to add |
| Strategy Studio | ✅ | 🟡 | ✅ | 🟡 | 🟡 | 🟡 | reactflow node styles bespoke |
| Paper Trading | ✅ | ✅ | ✅ | 🟡 | 🟡 | ✅ | = terminal |
| Replay | 🟡 | ✅ | ✅ | 🟡 | 🟡 | 🟡 | replay accent to tokenize |
| Backtesting | ✅ | ✅ | ✅ | 🟡 | 🟡 | ✅ | chart-first, good |
| Portfolio | ✅ | ✅ | ✅ | 🟡 | 🟡 | ✅ | heatmap tokens |
| Analytics | ✅ | ✅ | ✅ | 🟡 | 🟡 | ✅ | offline state ✅ |
| AI Intelligence | ✅ | ✅ | ✅ | 🟡 | 🟡 | ✅ | honest gating ✅ |
| Journal / Decisions / Memory | ✅ | ✅ | ✅ | 🟡 | 🟡 | ✅ | tables need virtualization |
| Risk Manager | ✅ | ✅ | ✅ | 🟡 | 🟡 | ✅ | correlation matrix good |
| Settings | ✅ | ✅ | ✅ | 🟡 | ✅ | ✅ | honest LOCKED rows ✅ |
| Auth (landing) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Tailwind, clean |

**Cross-cutting UI issues (dedupe/standardize):** two golds (`#EAB54F`/`#C9A24B`) → one brand + gold-deep; dashboard fonts not loaded → self-host; `--purple`=gold → rename; stale tokens (purple glow, `theme.ts`) → fix; two component sets → one shadcn/Radix library; tables not virtualized; intermediate breakpoints missing.

## 20. UX Audit Report (per-page, grounded)

| Dimension | Finding |
|---|---|
| **Navigation** | Grouped sidebar + deep links ✅; add breadcrumbs on deep pages + ⌘K palette 🔴. |
| **Interaction quality** | Hover/focus/active solid ✅; add tooltips (Radix) + bulk actions + undo 🔴. |
| **Feedback** | Toasts + confirm dialogs ✅; destructive actions confirm ✅; typed-confirm for go-live 🔴. |
| **Content honesty** | `"Not checked"`/`"Not connected"`/`"never faked"` markers ✅ (keep). |
| **Loading/empty/error** | `useLive` loading/error + offline card + `WhyNoTrades` ✅; not every page has a skeleton 🟡. |
| **Performance UX** | poller dedup/backoff/visibility-pause ✅; move to WebSocket push 🔴. |
| **Accessibility UX** | keyboard drawer + focus rings ✅; modal focus-trap + SR live regions + accessible charts 🔴. |
| **Consistency** | strong within each app; cross-app convergence pending 🟡. |

**Verdict:** UX is premium and honest within each app; the debt is cross-app unification + power-user affordances (palette, bulk, tooltips), not defects.

---

## 21. Design Consistency Checklist (gate every page)

- [ ] Colors from tokens only; no raw hex/rgb; every pair ≥ AA; gold not body.
- [ ] Spacing on the 8-pt scale; card 16–20, gutter 24–32.
- [ ] Type scale only; numbers mono + `tabular-nums`; ≤2 weights/surface.
- [ ] Components from the library; no one-off buttons/inputs; all states styled.
- [ ] Radius/shadow/border/elevation/z-index from tokens.
- [ ] Icons lucide, one version, `strokeWidth 1.9`, sized by scale.
- [ ] Charts: token palette; candle vs P&L colors correct; every mark = real data.
- [ ] Loading + empty + error states present.
- [ ] Responsive at 2560/1920/1600/1440/1280/1024/768/480; no horizontal body scroll.
- [ ] Motion from tokens; reduced-motion respected.
- [ ] Dark (and light) render correct via tokens.

## 22. Developer Implementation Checklist

- [ ] Token package generated → Tailwind config + CSS vars + Figma variables; drifts fixed (`--purple`→gold, glow, `theme.ts`).
- [ ] One gold resolved (`#EAB54F` brand / `#C9A24B` gold-deep).
- [ ] Inter + JetBrains Mono self-hosted in both apps; `tabular-nums` app-wide.
- [ ] Dashboard adopts Tailwind (or emits tokens as Tailwind) + shadcn/Radix.
- [ ] Migrate components family-by-family (Button→Input→Dialog→Table…), CSS classes aliased during migration.
- [ ] framer-motion app-wide + global reduced-motion in dashboard.
- [ ] Intermediate breakpoints (1024/1280/1440/1600/2560) + collapse/reflow rules.
- [ ] Radix for overlays/menus/tooltips/combobox/slider/date-picker.
- [ ] Storybook per component; visual-regression + axe gates in CI.
- [ ] Component props typed, `className`/`ref` forwarded, `asChild` where composable.

---

## 23. UI/UX Design System Readiness Score

| Dimension | Score | Notes |
|---|---:|---|
| Brand identity | 8/10 | N-monogram + gold/signal-blue; premium. |
| Color system | 7/10 | Rich; two-golds/stale tokens to resolve; light set new. |
| Typography | 5/10 | Good scale; fonts unloaded; tabular-nums not app-wide. |
| Spacing/layout | 7/10 | Real 8-pt + shell + IA; missing mid breakpoints. |
| Component library | 4/10 | Two bespoke sets; no shadcn/Radix — the core gap. |
| Chart system | 8/10 | Professional ECharts, rich markers. |
| Bot terminal | 8/10 | Dense, live, well-sectioned. |
| Motion | 5/10 | Landing good; app minimal/inconsistent. |
| Accessibility | 6/10 | Real wins; SR/charts/focus-trap gaps. |
| Responsive | 5/10 | Mobile drawer solid; mid tiers missing. |
| Tokens | 6/10 | Real JSON + CSS vars; three drifting sources. |
| Cross-app consistency | 3/10 | Two engines, two sets — headline debt. |

### **Overall: 6.5 / 10** — *"A premium, coherent identity implemented as two front-ends; the work is unification, not reinvention."*

The brand, ECharts terminal, and density are already institutional-grade. The gap is a **single shared token + component system** (this document) and the migration to it (§22). Executing the Developer Checklist lifts this to **9/10**, at which point a new page is provably identical to the rest of TradeLogX Nexus.

---

*End of Enterprise UI/UX Design System v1.0. Canonical; supersedes `UDS.md` and extends it to 23 sections. Gate every page on §21 (design) + §22 (implementation). Consistent with ADES (confidence tones, honesty markers), TES §9/§13 (terminal, replay), and API §4.5/§5 (filter/sort/paginate, WS).*
