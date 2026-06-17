import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";

interface EChartProps {
  option: EChartsOption;
  height?: number | string;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Reusable Apache ECharts wrapper — the only place that touches `echarts.init`.
 *
 * - Inits ONCE (not on every render).
 * - Updates the option reactively via `setOption(..., true)`.
 * - Resizes with its container via ResizeObserver (responsive in any card).
 * - Disposes on unmount (no memory leaks, no console errors).
 *
 * Drop this file in as-is; it has no project-specific dependencies.
 */
export default function EChart({ option, height = "100%", className, style }: EChartProps) {
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!elRef.current) return;
    const chart = echarts.init(elRef.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(elRef.current);

    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  return <div ref={elRef} className={className} style={{ width: "100%", height, ...style }} />;
}
