import { cn } from "@/lib/utils";

/**
 * Tradexa wordmark — an abstract upward "T/candlestick" mark in brushed gold.
 * Deliberately understated: no cartoon robot, no generic crypto coin.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("h-8 w-8", className)} aria-hidden="true">
      <defs>
        <linearGradient id="tx-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#E7D89A" />
          <stop offset="0.5" stopColor="#C8A94B" />
          <stop offset="1" stopColor="#A98E3A" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="9" fill="#0C0C0F" stroke="rgba(255,255,255,0.10)" />
      {/* candles rising */}
      <rect x="8" y="17" width="2.6" height="7" rx="1.3" fill="url(#tx-gold)" opacity="0.55" />
      <rect x="14.7" y="12" width="2.6" height="12" rx="1.3" fill="url(#tx-gold)" opacity="0.8" />
      <rect x="21.4" y="8" width="2.6" height="16" rx="1.3" fill="url(#tx-gold)" />
      {/* execution slash */}
      <path
        d="M7 20.5 L15 15 L22.7 9.5"
        fill="none"
        stroke="#fff"
        strokeOpacity="0.85"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      {!compact && (
        <span className="flex flex-col leading-none">
          <span className="text-[15px] font-bold tracking-tight text-white">Tradexa</span>
          <span className="text-[10px] font-medium uppercase tracking-[0.2em] text-gold/70">
            Trading Bot
          </span>
        </span>
      )}
    </span>
  );
}
