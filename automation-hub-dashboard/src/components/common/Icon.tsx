interface IconProps {
  name: string;
  size?: number;
  className?: string;
  color?: string;
}

// Minimal inline-SVG icon set (stroke-based, currentColor). Keeps the app
// dependency-free while covering every glyph the dashboard needs.
const PATHS: Record<string, string> = {
  menu: "M3 6h18M3 12h18M3 18h18",
  bell: "M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
  help: "M9.1 9a3 3 0 1 1 4.6 2.5c-.9.6-1.7 1.2-1.7 2.5M12 17h.01",
  theme: "M12 3v1M12 20v1M4 12H3M21 12h-1M6 6 5 5M19 19l-1-1M6 18l-1 1M19 5l-1 1M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  play: "M6 4l14 8-14 8V4z",
  pause: "M7 5h3v14H7zM14 5h3v14h-3z",
  plus: "M12 5v14M5 12h14",
  chevron: "M6 9l6 6 6-6",
  target: "M12 2v3M12 19v3M2 12h3M19 12h3",
  up: "M7 17 17 7M9 7h8v8",
  down: "M7 7l10 10M17 9v8H9",
  close: "M9 12h6M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8h.01M11 12h1v4h1",
  warning: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  check: "M20 6 9 17l-5-5",
  external: "M15 3h6v6M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
  robot: "M12 2v3M5 8h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zM9 13h.01M15 13h.01",
  layers: "M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  flask: "M9 3h6M10 3v6L5 19a1.5 1.5 0 0 0 1.4 2h11.2A1.5 1.5 0 0 0 19 19l-5-10V3",
  history: "M3 3v5h5M3.05 13a9 9 0 1 0 2.5-6.5L3 8M12 7v5l3 2",
  shield: "M12 2 4 5v6c0 5 3.5 8 8 11 4.5-3 8-6 8-11V5l-8-3z",
  chart: "M3 3v18h18M7 14l3-3 3 3 5-6",
  settings: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 6.6 19l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 12.6 2 2 0 1 1 3 11h.1a1.6 1.6 0 0 0 1.1-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 11 3.6V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 .9 2.4",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.5 3.8 5.6 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.6-3.8-9s1.3-6.5 3.8-9z",
  refresh: "M3 3v5h5M3.05 13a9 9 0 1 0 2.5-6.5L3 8",
  rocket: "M5 15c-1.5 1.5-2 5-2 5s3.5-.5 5-2c.9-.9.9-2.3 0-3.2a2.2 2.2 0 0 0-3 .2zM9 13l-2-2c1-4 4-8 9-8 0 5-4 8-8 9zM14.5 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z",
  wallet: "M3 7h15a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7zM3 7l2-3h11M16 13h.01",
  bot: "M12 2v3M5 8h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zM9 13h.01M15 13h.01M9 17h6",
  lock: "M5 11h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1zM8 11V7a4 4 0 0 1 8 0v4",
  skipBack: "M19 5v14l-9-7 9-7zM5 5v14",
  skipForward: "M5 5v14l9-7-9-7zM19 5v14",
};

export default function Icon({ name, size = 18, className, color }: IconProps) {
  const d = PATHS[name] ?? PATHS.info;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color ?? "currentColor"}
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  );
}
