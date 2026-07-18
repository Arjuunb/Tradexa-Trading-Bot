// TradeLogX Nexus mark — a two-tone "N" monogram (silver ascent + gold descent)
// inside a gold/steel ring, echoing an up/down market move. Matches the official
// brand logo and the app favicon. Shared across the app so it carries ONE brand.
export default function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 96 96" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-label="TradeLogX Nexus">
      <defs>
        <linearGradient id="nxSplit" x1="24" y1="0" x2="72" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#E9EEF3" />
          <stop offset=".46" stopColor="#AEB7C2" />
          <stop offset=".54" stopColor="#E7C766" />
          <stop offset="1" stopColor="#C6961F" />
        </linearGradient>
        <linearGradient id="nxRing" x1="14" y1="14" x2="82" y2="82" gradientUnits="userSpaceOnUse">
          <stop stopColor="#E7C766" /><stop offset=".5" stopColor="#8A929C" /><stop offset="1" stopColor="#C6961F" />
        </linearGradient>
      </defs>
      <circle cx="48" cy="48" r="41" stroke="url(#nxRing)" strokeWidth="2.6" opacity="0.85" />
      <path d="M31 70 V32 M31 32 L65 70 M65 70 V26" stroke="url(#nxSplit)" strokeWidth="11" strokeLinecap="butt" strokeLinejoin="miter" />
      <path d="M31 14 L40 30 H22 Z" fill="#E9EEF3" />
      <path d="M65 82 L56 66 H74 Z" fill="#C6961F" />
    </svg>
  );
}
