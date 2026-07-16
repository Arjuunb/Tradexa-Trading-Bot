# Audit Phase 3 — polish

The audit's Low-priority polish items. Dashboard-only, no engine changes. Scope
was deliberately kept to items with real user value; the "convert all 47 files
from the custom `Icon` set to lucide" idea was **rejected** — the custom SVG set
is already the app's consistent system and renders fine, so a mass rewrite would
be churn and risk with no user-visible gain.

## A11y — gain/loss no longer relies on colour alone
Several P&L / expectancy / net-exposure / Sharpe·Sortino / net-R values were
shown green-or-red with **no sign** — so a positive vs negative reading depended
entirely on colour (fails WCAG 1.4.1 "use of colour"; invisible to colour-blind
users and to screen readers). Added `src/lib/format.ts` with `signedMoney` /
`signedNum` (always a leading `+`/`−`) and applied it at the colour-coded sites:
Sidebar realized P&L, Portfolio net exposure, BotHealth today's P&L, Strategy
Proof (expectancy, Sharpe, Sortino, net P&L, walk-forward + per-symbol/session R),
Memory trade P&L, Strategies realized P&L + net-R. The green/red classes stay —
now the sign carries the same meaning without colour.

## Icons — removed the dead map, killed emoji-as-icons
- Deleted the unused `NAV_ICON` export from `Icon.tsx` — a stale duplicate of the
  Sidebar's live `NAV_LUCIDE` map that the two had already drifted apart on.
- Replaced the raw `⏮`/`⏭` emoji on Replay's jump-to-trade buttons (which sat
  right next to proper `<Icon>` step buttons) with new `skipBack`/`skipForward`
  glyphs in the icon set, so the whole control cluster is one visual system.
  (Transient toast check-marks like "Saved ✅" were left — they're friendly
  affordances, not part of the persistent icon system.)

## Mobile — a real off-canvas nav drawer
Below 720px the sidebar used to stay pinned as a 74px icon rail with no labels,
permanently eating horizontal space and un-dismissable. It's now an off-canvas
**drawer**: the header hamburger slides the full-label sidebar in over a dim
scrim (`.nav-backdrop`); tapping the scrim, pressing Escape, or picking a page
closes it, and the content gets the full viewport width. On desktop the
hamburger still collapses the rail to icons as before — the toggle picks
behaviour by viewport (`matchMedia`), and growing back to desktop width clears
any open drawer state.

## Drive-by type fix
`RiskPresets` passed `tone="gold"` to `Badge`, but `gold` wasn't in the `Tone`
union — a pre-existing type error that also rendered the "active" badge with a
broken (undefined) colour. Added a `gold` tone mapped to the brand accent
(`#eab54f`), so the badge renders and `tsc --noEmit` is clean.

## Left as-is (intentional)
- The custom `Icon` SVG set stays the app-wide system; lucide stays scoped to the
  nav rail. Not unifying — both are internally consistent.
- "Automation Hub" (infra/backend) vs "Tradexa" (product) naming: the few
  operator help strings (`cd automation-hub && uvicorn …`) are accurate
  commands, not product copy, so they were left untouched.
