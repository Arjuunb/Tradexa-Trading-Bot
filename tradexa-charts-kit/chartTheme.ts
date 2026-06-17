// Shared chart design tokens — the single source of the "clean, professional"
// look. Tweak these in one place and every chart updates. Framework-agnostic.

export const palette = {
  purple: "#8b5cf6",
  green: "#22c55e",
  red: "#ef4444",
  amber: "#f59e0b",
  blue: "#3b82f6",
  cyan: "#06b6d4",
  pink: "#ec4899",
  lime: "#84cc16",
};

// Ordered palette for multi-series / pie slices.
export const series = [
  palette.purple, palette.green, palette.blue, palette.amber,
  palette.red, palette.cyan, palette.pink, palette.lime,
];

export const colors = {
  text: "#d6dde6",       // primary labels
  textDim: "#8a93a6",    // axis labels / muted
  axis: "#2a3350",       // axis lines
  grid: "#161d30",       // split lines (barely-there gridlines)
  tooltipBg: "rgba(13,18,32,0.95)",
  tooltipBorder: "#2a3350",
};

// A dark, glassy tooltip used by every chart.
export const tooltipStyle = {
  backgroundColor: colors.tooltipBg,
  borderColor: colors.tooltipBorder,
  textStyle: { color: "#e6eaf2", fontSize: 12 },
};

// Category (x) axis preset.
export const categoryAxis = (data: (string | number)[]) => ({
  type: "category" as const,
  data,
  boundaryGap: false,
  axisLine: { lineStyle: { color: colors.axis } },
  axisTick: { show: false },
  axisLabel: { color: colors.textDim, fontSize: 11 },
});

// Value (y) axis preset.
export const valueAxis = (formatter?: (v: number) => string) => ({
  type: "value" as const,
  scale: true,
  axisLabel: { color: colors.textDim, fontSize: 11, formatter },
  splitLine: { lineStyle: { color: colors.grid } },
});

// Tight default grid so charts sit flush inside cards.
export const grid = { left: 50, right: 16, top: 16, bottom: 26 };

// Smooth gradient area fill from a base color (top → transparent).
export const areaFill = (color: string) => ({
  color: {
    type: "linear" as const, x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [
      { offset: 0, color: `${color}55` },
      { offset: 1, color: `${color}05` },
    ],
  },
});
