// Tradexa mark — the same brushed-gold rising candles + execution slash used by
// the landing/settings app, so both apps carry ONE brand. Crisp at any size.
export default function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Tradexa Trading Bot">
      <defs>
        <linearGradient id="tx-gold-dash" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#E7D89A" />
          <stop offset="0.5" stopColor="#C8A94B" />
          <stop offset="1" stopColor="#A98E3A" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="9" fill="#0C0C0F" stroke="rgba(255,255,255,0.10)" />
      {/* candles rising */}
      <rect x="8" y="17" width="2.6" height="7" rx="1.3" fill="url(#tx-gold-dash)" opacity="0.55" />
      <rect x="14.7" y="12" width="2.6" height="12" rx="1.3" fill="url(#tx-gold-dash)" opacity="0.8" />
      <rect x="21.4" y="8" width="2.6" height="16" rx="1.3" fill="url(#tx-gold-dash)" />
      {/* execution slash */}
      <path
        d="M7 20.5 L15 15 L22.7 9.5"
        fill="none"
        stroke="#ffffff"
        strokeOpacity="0.85"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
