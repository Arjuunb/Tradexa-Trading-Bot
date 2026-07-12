/**
 * Ambient page backdrop: a fine, faintly panning technical grid with a single
 * restrained gold bloom. Deliberately spare — the depth should read as an
 * instrument surface, not decoration.
 */
export function Background() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-ink">
      {/* restrained gradient bloom */}
      <div className="absolute -top-48 left-1/2 h-[34rem] w-[46rem] -translate-x-1/2 rounded-full bg-gold/[0.045] blur-[130px]" />

      {/* fine technical grid — the primary texture */}
      <div className="absolute inset-0 animate-grid-pan bg-grid-lines [background-size:28px_28px] mask-fade-b opacity-60" />
      {/* coarse accent grid for depth */}
      <div className="absolute inset-0 bg-grid-lines [background-size:140px_140px] opacity-[0.35] mask-fade-b" />

      {/* vignette */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_58%,rgba(0,0,0,0.6))]" />
    </div>
  );
}
