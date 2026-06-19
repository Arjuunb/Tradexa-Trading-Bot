import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import type { ReplayData } from "../../lib/api";

interface Props {
  data: ReplayData;
  index: number; // current replay bar (inclusive); chart shows [0..index]
  height?: number;
}

/** TradingView-style candlestick + volume + EMA/VWAP + trade markers.
 *  Renders ONLY candles up to `index` — the future is never drawn. */
export default function CandleChart({ data, index, height = 460 }: Props) {
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!elRef.current) return;
    const chart = echarts.init(elRef.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(elRef.current);
    return () => { ro.disconnect(); chart.dispose(); chartRef.current = null; };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const end = Math.min(index + 1, data.candles.length);
    const c = data.candles.slice(0, end);
    const cats = c.map((b) => b.t.replace("T", " ").slice(5, 16));
    const ohlc = c.map((b) => [b.o, b.c, b.l, b.h]); // ECharts: open,close,low,high
    const vol = c.map((b) => ({ value: b.v, itemStyle: { color: b.c >= b.o ? "#089981" : "#f23645" } }));
    const ema20 = data.overlays.ema20.slice(0, end);
    const ema50 = data.overlays.ema50.slice(0, end);
    const vwap = data.overlays.vwap.slice(0, end);

    // structure markers up to now
    const markPts = data.markers
      .filter((m) => m.idx < end)
      .map((m) => ({
        name: m.type,
        coord: [m.idx, m.price],
        symbol: m.type === "Entry" ? "pin" : "circle",
        symbolSize: m.type === "Entry" ? 26 : 9,
        itemStyle: { color: m.side === "bull" ? "#089981" : "#f23645" },
        label: { show: m.type === "Entry", formatter: m.type, position: "top", color: "#cfd6e4", fontSize: 9 },
      }));

    // active trade SL/TP lines (the most recent trade whose entry<=index and not yet exited)
    const active = [...data.trades].reverse().find((t) => t.entry_idx <= index && (t.exit_idx === null || t.exit_idx > index));
    const markLines: any[] = [];
    if (active) {
      markLines.push(
        { yAxis: active.entry, lineStyle: { color: "#8a93a6", type: "solid" }, label: { formatter: "Entry", color: "#8a93a6" } },
        { yAxis: active.sl, lineStyle: { color: "#f23645", type: "dashed" }, label: { formatter: "SL", color: "#f23645" } },
        { yAxis: active.tp, lineStyle: { color: "#089981", type: "dashed" }, label: { formatter: "TP", color: "#089981" } },
      );
    }

    const option: EChartsOption = {
      backgroundColor: "transparent",
      animation: false,
      grid: [
        { left: 56, right: 16, top: 12, height: "66%" },
        { left: 56, right: 16, top: "76%", height: "16%" },
      ],
      xAxis: [
        { type: "category", data: cats, axisLine: { lineStyle: { color: "#2a3350" } }, axisLabel: { color: "#8a93a6", fontSize: 10 }, gridIndex: 0 },
        { type: "category", data: cats, gridIndex: 1, axisLabel: { show: false }, axisLine: { lineStyle: { color: "#2a3350" } } },
      ],
      yAxis: [
        { scale: true, position: "right", axisLabel: { color: "#8a93a6", fontSize: 10 }, splitLine: { lineStyle: { color: "#161d30" } }, gridIndex: 0 },
        { scale: true, gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      tooltip: { trigger: "axis", backgroundColor: "rgba(13,18,32,0.95)", borderColor: "#2a3350", textStyle: { color: "#e6eaf2", fontSize: 11 } },
      series: [
        {
          type: "candlestick", data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
          itemStyle: { color: "#089981", color0: "#f23645", borderColor: "#089981", borderColor0: "#f23645" },
          markPoint: { data: markPts as any, silent: true },
          markLine: { symbol: "none", data: markLines as any, silent: true },
        },
        { type: "line", data: ema20, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, smooth: true, lineStyle: { color: "#3b82f6", width: 1.3 }, name: "EMA20" },
        { type: "line", data: ema50, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, smooth: true, lineStyle: { color: "#f59e0b", width: 1.3 }, name: "EMA50" },
        { type: "line", data: vwap, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, lineStyle: { color: "#8b5cf6", width: 1.1, type: "dashed" }, name: "VWAP" },
        { type: "bar", data: vol as any, xAxisIndex: 1, yAxisIndex: 1 },
      ],
    };
    chart.setOption(option, true);
  }, [data, index]);

  return <div ref={elRef} style={{ width: "100%", height }} />;
}
