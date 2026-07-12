import { motion } from "framer-motion";

// Deterministic particle field (no Math.random at module scope → stable SSR/build).
const PARTICLES = Array.from({ length: 18 }, (_, i) => ({
  left: (i * 53) % 100,
  top: (i * 37 + 11) % 100,
  size: (i % 3) + 1.5,
  delay: (i % 6) * 0.7,
  duration: 7 + (i % 5),
}));

/**
 * Ambient page backdrop: a slowly panning trading grid, a soft gold gradient
 * bloom at the top, and a few drifting particles. Subtle by design — it must
 * read as institutional depth, never as decoration.
 */
export function Background() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-ink">
      {/* gradient bloom */}
      <div className="absolute inset-0 bg-radial-fade" />
      <div className="absolute -top-40 left-1/2 h-[38rem] w-[38rem] -translate-x-1/2 rounded-full bg-gold/[0.06] blur-[120px]" />
      <div className="absolute bottom-0 right-0 h-[30rem] w-[30rem] rounded-full bg-emerald/[0.04] blur-[130px]" />

      {/* panning grid */}
      <div className="absolute inset-0 animate-grid-pan bg-grid-lines [background-size:40px_40px] mask-fade-b opacity-70" />

      {/* particles */}
      {PARTICLES.map((p, i) => (
        <motion.span
          key={i}
          className="absolute rounded-full bg-gold/40"
          style={{ left: `${p.left}%`, top: `${p.top}%`, width: p.size, height: p.size }}
          animate={{ y: [0, -22, 0], opacity: [0.15, 0.5, 0.15] }}
          transition={{ duration: p.duration, delay: p.delay, repeat: Infinity, ease: "easeInOut" }}
        />
      ))}

      {/* vignette */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_55%,rgba(0,0,0,0.55))]" />
    </div>
  );
}
