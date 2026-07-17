import { cn } from "@/lib/utils";

/**
 * TradeLogX Nexus mark — a central intelligence "nexus" node linking market,
 * strategy, risk and execution. Gold core (the decision), blue links (data flow).
 * Deliberately institutional: no cartoon robot, no generic crypto coin.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("h-8 w-8", className)} aria-hidden="true">
      <circle cx="16" cy="16" r="9.2" stroke="rgba(201,162,75,0.35)" strokeWidth="1" fill="none" />
      <g stroke="#3E7BD6" strokeWidth="1.4">
        <path d="M16 16 5 6M16 16l11-10M16 16 5 26M16 16l11 10" />
      </g>
      <g fill="#6EA3EC">
        <circle cx="5" cy="6" r="2.4" />
        <circle cx="27" cy="6" r="2.4" />
        <circle cx="5" cy="26" r="2.4" />
        <circle cx="27" cy="26" r="2.4" />
      </g>
      <circle cx="16" cy="16" r="4.4" fill="#C9A24B" />
    </svg>
  );
}

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      {!compact && (
        <span className="flex flex-col leading-none">
          <span className="text-[15px] font-bold tracking-tight text-white">TradeLogX</span>
          <span className="text-[10px] font-medium uppercase tracking-[0.28em] text-gold/80">
            Nexus
          </span>
        </span>
      )}
    </span>
  );
}
