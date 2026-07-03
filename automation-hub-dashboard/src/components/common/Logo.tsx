// Automation Hub logo — a gradient badge with an upward trend line + node and
// subtle candlesticks. Crisp at any size; themed to the dashboard accent.
export default function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Automation Hub">
      <defs>
        <linearGradient id="ah-bg" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stopColor="#eab54f" />
          <stop offset="1" stopColor="#3b82f6" />
        </linearGradient>
        <linearGradient id="ah-line" x1="10" y1="32" x2="38" y2="13" gradientUnits="userSpaceOnUse">
          <stop stopColor="#ffffff" />
          <stop offset="1" stopColor="#e9d5ff" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="12" fill="url(#ah-bg)" />
      {/* candlesticks (volume/price hint) */}
      <rect x="12" y="26" width="2.4" height="11" rx="1.2" fill="#ffffff" opacity="0.30" />
      <rect x="19" y="22" width="2.4" height="15" rx="1.2" fill="#ffffff" opacity="0.30" />
      <rect x="26" y="28" width="2.4" height="9" rx="1.2" fill="#ffffff" opacity="0.30" />
      <rect x="33" y="19" width="2.4" height="18" rx="1.2" fill="#ffffff" opacity="0.30" />
      {/* uptrend line */}
      <path d="M11 31 L20 23 L27 27 L37 14" stroke="url(#ah-line)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      {/* node at the peak */}
      <circle cx="37" cy="14" r="4.5" fill="#3b82f6" stroke="#ffffff" strokeWidth="2.5" />
    </svg>
  );
}
