import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A page-owned backdrop.
 *
 * The app renders one shared gold-bloom backdrop for the landing and auth
 * surfaces. Each dedicated page needs its own base colour and texture instead —
 * graphite under /engine, navy under /security — so this paints an opaque layer
 * at the same depth, and the app skips the shared one on these routes.
 *
 * `base` must be opaque: a translucent page backdrop would let the shared gold
 * bloom bleed through and every page would drift back towards the same hue.
 */
export function Ambient({ base, children, className }: { base: string; children?: ReactNode; className?: string }) {
  return (
    <div aria-hidden className={cn("pointer-events-none fixed inset-0 -z-10 overflow-hidden", base, className)}>
      {children}
    </div>
  );
}
