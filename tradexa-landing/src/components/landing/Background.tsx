/**
 * Ambient page backdrop. Three quiet layers on a barely-warm charcoal base:
 * the brand-gold bloom up top, a whisper of the profit-emerald low right
 * (the same duotone the product uses for money), and a faint ember low left
 * to keep the long scroll from going dead. The fine grid is warm-tinted so
 * the texture belongs to the palette instead of sitting on it. Everything
 * drifts slowly; `motion-safe` keeps it still for reduced-motion users.
 */
export function Background() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-ink bg-page-depth">
      {/* primary gold bloom — the light source */}
      <div className="absolute -top-48 left-1/2 h-[34rem] w-[46rem] -translate-x-1/2 rounded-full bg-gold/[0.05] blur-[130px] motion-safe:animate-bloom" />
      {/* counterweight: deep emerald, very low — reads as depth, not color */}
      <div className="absolute -bottom-56 right-[-12rem] h-[30rem] w-[40rem] rounded-full bg-emerald-deep/[0.05] blur-[150px] motion-safe:animate-bloom-slow" />
      {/* faint ember so the mid-scroll left edge isn't dead black */}
      <div className="absolute bottom-1/4 left-[-14rem] h-[24rem] w-[30rem] rounded-full bg-gold-deep/[0.035] blur-[140px]" />

      {/* fine technical grid — the primary texture (warm-tinted) */}
      <div className="absolute inset-0 animate-grid-pan bg-grid-lines [background-size:28px_28px] mask-fade-b opacity-60" />
      {/* coarse accent grid for depth */}
      <div className="absolute inset-0 bg-grid-lines [background-size:140px_140px] opacity-[0.35] mask-fade-b" />

      {/* vignette pulls the eye to the content column */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_58%,rgba(0,0,0,0.6))]" />
    </div>
  );
}
