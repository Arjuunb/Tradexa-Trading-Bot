// TradeLogX Nexus mark — a central intelligence node linking market, strategy,
// risk and execution (gold core, blue data links). Shared by both apps so they
// carry ONE brand. Crisp at any size.
export default function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="TradeLogX Nexus">
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
