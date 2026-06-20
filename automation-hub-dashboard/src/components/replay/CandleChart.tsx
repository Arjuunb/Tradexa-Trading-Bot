import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import type { ReplayData } from "../../lib/api";

interface Props {
  data: ReplayData;
  index: number; // current replay bar (inclusive); chart shows [0..index]
  height?: number;
}

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });
const volFmt = (v: number) => (v >= 1_000_000 ? (v / 1e6).toFixed(1) + "M" : v >= 1000 ? (v / 1000).toFixed(0) + "K" : v.toFixed(0));
const WINDOW = 130; // visible candles by default — proper spacing instead of cramming all

/** TradingView-style candlestick: price axis (right), time axis (bottom),
 *  zoom/scroll/pan, crosshair, current-price tag, OHLC readout, EMA/VWAP,
 *  entry/exit markers, SL/TP lines + risk/reward zones, volume panel.
 *  Renders ONLY candles up to `index` — the future is never drawn. */
export default function CandleChart({ data, index, height = 520 }: Props) {
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
    if (c.length === 0) { chart.clear(); return; }
    const cats = c.map((b) => b.t.replace("T", " ").slice(5, 16));
    const ohlc = c.map((b) => [b.o, b.c, b.l, b.h]); // ECharts: open,close,low,high
    const vol = c.map((b) => ({ value: b.v, itemStyle: { color: b.c >= b.o ? "#089981" : "#f23645" } }));
    const ema20 = data.overlays.ema20.slice(0, end);
    const ema50 = data.overlays.ema50.slice(0, end);
    const vwap = data.overlays.vwap.slice(0, end);

    const last = c[c.length - 1];
    const prev = c[c.length - 2];
    const chg = prev ? ((last.c - prev.c) / prev.c) * 100 : 0;
    const upCol = last.c >= last.o ? "#089981" : "#f23645";

    // structure + entry/exit markers up to now
    const markPts = data.markers
      .filter((m) => m.idx < end)
      .map((m) => ({
        name: m.type, coord: [m.idx, m.price],
        symbol: m.type === "Entry" ? "pin" : "circle",
        symbolSize: m.type === "Entry" ? 26 : m.type === "TP1" ? 14 : 9,
        itemStyle: { color: m.side === "bull" ? "#089981" : "#f23645" },
        label: { show: m.type === "Entry", formatter: m.type, position: "top", color: "#cfd6e4", fontSize: 9 },
      }));
    // exit markers (X) from closed trades
    for (const t of data.trades) {
      if (t.exit_idx !== null && t.exit_idx <= index && t.exit !== null) {
        markPts.push({
          name: "Exit", coord: [t.exit_idx, t.exit], symbol: "diamond", symbolSize: 13,
          itemStyle: { color: t.result === "Winner" ? "#089981" : "#f23645" },
          label: { show: false, formatter: "", position: "bottom", color: "#cfd6e4", fontSize: 9 },
        } as any);
      }
    }

    const active = [...data.trades].reverse().find((t) => t.entry_idx <= index && (t.exit_idx === null || t.exit_idx > index));
    const markLines: any[] = [
      // current price tag (right axis)
      { yAxis: last.c, symbol: "none", lineStyle: { color: "#5b6478", type: "dashed", opacity: 0.6 },
        label: { formatter: fmt(last.c), position: "end", color: "#fff", backgroundColor: upCol, padding: [2, 4], fontSize: 10, borderRadius: 3 } },
    ];
    const tradeAreas: any[] = [];
    if (active) {
      const beMoved = active.tp1_idx !== null && active.tp1_idx <= index;
      const slLevel = beMoved ? active.entry : active.sl;
      markLines.push(
        { yAxis: active.entry, symbol: "none", lineStyle: { color: "#8a93a6" }, label: { formatter: "Entry " + fmt(active.entry), color: "#8a93a6", fontSize: 9 } },
        { yAxis: slLevel, symbol: "none", lineStyle: { color: "#f23645", type: "dashed" }, label: { formatter: (beMoved ? "BE " : "SL ") + fmt(slLevel), color: "#f23645", fontSize: 9 } },
        { yAxis: active.tp, symbol: "none", lineStyle: { color: "#089981", type: "dashed" }, label: { formatter: "TP " + fmt(active.tp), color: "#089981", fontSize: 9 } },
      );
      if (active.tp1 !== null)
        markLines.push({ yAxis: active.tp1, symbol: "none", lineStyle: { color: "#089981", type: "dotted", opacity: 0.7 }, label: { formatter: "TP1", color: "#089981", fontSize: 9 } });
      // risk zone (entry↔SL) red, reward zone (entry↔TP) green
      tradeAreas.push([{ xAxis: active.entry_idx, yAxis: active.entry, itemStyle: { color: "rgba(242,54,69,0.10)" } }, { xAxis: end - 1, yAxis: slLevel }]);
      tradeAreas.push([{ xAxis: active.entry_idx, yAxis: active.entry, itemStyle: { color: "rgba(8,153,129,0.10)" } }, { xAxis: end - 1, yAxis: active.tp }]);
    }
    // S/R levels
    for (const z of data.zones) {
      if (z.price !== undefined)
        markLines.push({ yAxis: z.price, symbol: "none", lineStyle: { color: z.type === "support" ? "#089981" : "#f23645", type: "dotted", opacity: 0.5 }, label: { formatter: z.type === "support" ? "S" : "R", color: "#8a93a6", fontSize: 9 } });
    }
    // supply/demand order-block zones
    const zoneAreas = data.zones
      .filter((z) => z.left_idx !== undefined && z.left_idx <= index).slice(-8)
      .map((z) => ([
        { xAxis: z.left_idx, yAxis: z.top, itemStyle: { color: z.type === "demand" ? "rgba(8,153,129,0.12)" : "rgba(242,54,69,0.12)" } },
        { xAxis: end - 1, yAxis: z.bottom },
      ]));

    const startV = Math.max(0, end - WINDOW);
    const option: EChartsOption = {
      backgroundColor: "transparent",
      animation: false,
      title: {
        left: 58, top: 4, textStyle: { color: upCol, fontSize: 11, fontWeight: 500 },
        text: `${data.meta.symbol} ${data.meta.timeframe}   O ${fmt(last.o)}  H ${fmt(last.h)}  L ${fmt(last.l)}  C ${fmt(last.c)}  Vol ${volFmt(last.v)}   ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`,
      },
      axisPointer: { link: [{ xAxisIndex: "all" }], label: { backgroundColor: "#1e2438" } },
      legend: { data: ["EMA20", "EMA50", "VWAP"], top: 4, right: 64, itemWidth: 14, itemHeight: 8,
        textStyle: { color: "#8a93a6", fontSize: 10 }, icon: "roundRect" },
      grid: [
        { left: 56, right: 64, top: 28, height: "58%" },
        { left: 56, right: 64, top: "72%", height: "13%" },
      ],
      xAxis: [
        { type: "category", data: cats, gridIndex: 0, boundaryGap: true,
          axisLine: { lineStyle: { color: "#2a3350" } }, axisTick: { show: false },
          axisLabel: { show: false }, axisPointer: { label: { show: true } } },
        { type: "category", data: cats, gridIndex: 1, boundaryGap: true,
          axisLine: { lineStyle: { color: "#2a3350" } }, axisTick: { show: false },
          axisLabel: { color: "#8a93a6", fontSize: 10, hideOverlap: true } },
      ],
      yAxis: [
        { scale: true, position: "right", gridIndex: 0,
          axisLabel: { color: "#8a93a6", fontSize: 10, formatter: (v: number) => fmt(v) },
          splitLine: { lineStyle: { color: "#161d30" } } },
        { scale: true, position: "right", gridIndex: 1, name: "Vol", nameTextStyle: { color: "#5b6478", fontSize: 9 },
          axisLabel: { color: "#5b6478", fontSize: 9, formatter: (v: number) => volFmt(v) }, splitLine: { show: false } },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], startValue: startV, endValue: end - 1, zoomOnMouseWheel: true, moveOnMouseMove: true, minValueSpan: 20 },
        { type: "slider", xAxisIndex: [0, 1], startValue: startV, endValue: end - 1, height: 18, bottom: 6,
          backgroundColor: "rgba(30,36,56,0.4)", fillerColor: "rgba(139,92,246,0.15)", borderColor: "#2a3350",
          handleStyle: { color: "#8b5cf6" }, textStyle: { color: "#8a93a6", fontSize: 9 }, dataBackground: { lineStyle: { color: "#2a3350" }, areaStyle: { color: "#161d30" } } },
      ],
      tooltip: {
        trigger: "axis", axisPointer: { type: "cross", crossStyle: { color: "#5b6478" } },
        backgroundColor: "rgba(13,18,32,0.96)", borderColor: "#2a3350", textStyle: { color: "#e6eaf2", fontSize: 11 },
        formatter: (ps: any) => {
          const i = ps[0].dataIndex; const b = c[i]; if (!b) return "";
          const up = b.c >= b.o;
          return `<b>${cats[i]}</b><br/>O ${fmt(b.o)}  H ${fmt(b.h)}<br/>L ${fmt(b.l)}  <span style="color:${up ? "#089981" : "#f23645"}">C ${fmt(b.c)}</span><br/>Vol ${volFmt(b.v)}`;
        },
      },
      series: [
        {
          type: "candlestick", data: ohlc, xAxisIndex: 0, yAxisIndex: 0, barMaxWidth: 14,
          itemStyle: { color: "#089981", color0: "#f23645", borderColor: "#089981", borderColor0: "#f23645" },
          markPoint: { data: markPts as any, silent: true },
          markLine: { symbol: "none", data: markLines as any, silent: true },
          markArea: { silent: true, data: [...zoneAreas, ...tradeAreas] as any },
        },
        { type: "line", data: ema20, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, smooth: true, lineStyle: { color: "#3b82f6", width: 1.3 }, name: "EMA20" },
        { type: "line", data: ema50, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, smooth: true, lineStyle: { color: "#f59e0b", width: 1.3 }, name: "EMA50" },
        { type: "line", data: vwap, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, lineStyle: { color: "#8b5cf6", width: 1.1, type: "dashed" }, name: "VWAP" },
        { type: "bar", data: vol as any, xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 14 },
      ],
    };
    chart.setOption(option, true);
  }, [data, index]);

  return <div ref={elRef} style={{ width: "100%", height }} />;
}
