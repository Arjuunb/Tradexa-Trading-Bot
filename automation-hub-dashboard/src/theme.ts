// Central design tokens, shared with CSS variables in index.css.
export const COLORS = {
  bg: "#080b14",
  card: "#101a2e",
  purple: "#eab54f",
  purpleSoft: "rgba(234, 181, 79, 0.18)",
  green: "#22c55e",
  greenSoft: "rgba(34, 197, 94, 0.16)",
  red: "#ef4444",
  redSoft: "rgba(239, 68, 68, 0.16)",
  amber: "#f59e0b",
  blue: "#3b82f6",
  grid: "#1c2336",
  axis: "#5b6478",
  text: "#e6eaf2",
  dim: "#8a93a6",
} as const;

export const statusColor = (status: string): string => {
  switch (status) {
    case "Live":
      return COLORS.purple;
    case "Running":
      return COLORS.green;
    case "Paper":
      return COLORS.blue;
    default:
      return COLORS.dim;
  }
};
