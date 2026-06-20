import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import type { ReplayData } from "../../lib/api";

export interface ChartToggles {
  ema8: boolean; ema20: boolean; ema30: boolean; ema50: boolean;
  sma20: boolean; sma50: boolean; vwap: boolean; bb: boolean; volume: boolean;
  structure: boolean; zones: boolean;
  osc: "none" | "rsi" | "macd" | "atr";
}

interface Props {
  data: ReplayData;
  index: number; // current replay bar (inclusive); chart shows [0..index]
  toggles: ChartToggles;
  height?: number;
}

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });
const volFmt = (v: number) => (v >= 1_000_000 ? (v / 1e6).toFixed(1) + "M" : v >= 1000 ? (v / 1000).toFixed(0) + "K" : v.toFixed(0));
const WINDOW = 130; // visible candles by default — proper spacing instead of cramming all
const num = (a: (number | null)[] | undefined, end: number) => (a ? a.slice(0, end) : []);

/** TradingView-style candlestick: price axis (right), time axis (bottom),
 *  zoom/scroll/pan, crosshair, current-price tag, OHLC readout, toggleable
 *  indicators (EMA/SMA/VWAP/Bollinger), entry/exit markers, SL/TP lines +
 *  risk/reward zones, a volume pane and an optional oscillator pane (RSI /
 *  MACD / ATR). Renders ONLY candles up to `index` — the future is never drawn.
 *  Every indicator drawn here is a real, server-computed causal series. */
export default function CandleChart({ data, index, toggles, height = 520 }: Props) {
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

  // resize when the container height changes (e.g. fullscreen)
  useEffect(() => { chartRef.current?.resize(); }, [height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const end = Math.min(index + 1, data.candles.length);
    const c = data.candles.slice(0, end);
    if (c.length === 0) { chart.clear(); return; }
    const ov = data.overlays as Record<string, (number | null)[]>;
    const cats = c.map((b) => b.t.replace("T", " ").slice(5, 16));
    const ohlc = c.map((b) => [b.o, b.c, b.l, b.h]); // ECharts: open,close,low,high
    const vol = c.map((b) => ({ value: b.v, itemStyle: { color: b.c >= b.o ? "#089981" : "#f23645" } }));

    const last = c[c.length - 1];
    const prev = c[c.length - 2];
    const chg = prev ? ((last.c - prev.c) / prev.c) * 100 : 0;
    const upCol = last.c >= last.o ? "#089981" : "#f23645";

    // ---- dynamic pane layout: price + optional volume + optional oscillator ----
    const hasVol = toggles.volume;
    const hasOsc = toggles.osc !== "none";
    const sub = (hasVol ? 1 : 0) + (hasOsc ? 1 : 0);
    const L = sub === 0 ? { price: [6, 80] as [number, number] }
      : sub === 1 ? { price: [6, 58] as [number, number], a: [70, 18] as [number, number] }
        : { price: [6, 46] as [number, number], a: [58, 13] as [number, number], b: [75, 16] as [number, number] };
    const seg = (k: "price" | "a" | "b") => (L as any)[k] as [number, number];
    const grids: any[] = [{ left: 56, right: 64, top: `${seg("price")[0]}%`, height: `${seg("price")[1]}%` }];
    let volGrid = -1, oscGrid = -1;
    if (hasVol) { volGrid = grids.length; const s = seg("a"); grids.push({ left: 56, right: 64, top: `${s[0]}%`, height: `${s[1]}%` }); }
    if (hasOsc) { oscGrid = grids.length; const s = seg(hasVol ? "b" : "a"); grids.push({ left: 56, right: 64, top: `${s[0]}%`, height: `${s[1]}%` }); }

    const xAxis: any[] = grids.map((_, gi) => ({
      type: "category", data: cats, gridIndex: gi, boundaryGap: true,
      axisLine: { lineStyle: { color: "#2a3350" } }, axisTick: { show: false },
      axisLabel: gi === grids.length - 1 ? { color: "#8a93a6", fontSize: 10, hideOverlap: true } : { show: false },
      axisPointer: { label: { show: gi === grids.length - 1 } },
    }));
    const yAxis: any[] = [{ scale: true, position: "right", gridIndex: 0,
      axisLabel: { color: "#8a93a6", fontSize: 10, formatter: (v: number) => fmt(v) },
      splitLine: { lineStyle: { color: "#161d30" } } }];
    if (hasVol) yAxis.push({ scale: true, position: "right", gridIndex: volGrid, name: "Vol",
      nameTextStyle: { color: "#5b6478", fontSize: 9 },
      axisLabel: { color: "#5b6478", fontSize: 9, formatter: (v: number) => volFmt(v) }, splitLine: { show: false } });
    if (hasOsc) yAxis.push({ scale: toggles.osc !== "rsi", min: toggles.osc === "rsi" ? 0 : undefined,
      max: toggles.osc === "rsi" ? 100 : undefined, position: "right", gridIndex: oscGrid,
      name: toggles.osc.toUpperCase(), nameTextStyle: { color: "#5b6478", fontSize: 9 },
      axisLabel: { color: "#5b6478", fontSize: 9 }, splitLine: { show: false } });

    // ---- markers: structure + entry, plus closed-trade exits ----
    const STRUCT = new Set(["Sweep", "BOS/CHoCH", "FVG"]);
    const markPts = data.markers
      .filter((m) => m.idx < end && (toggles.structure || !STRUCT.has(m.type)))
      .map((m) => ({
        name: m.type, coord: [m.idx, m.price],
        symbol: m.type === "Entry" ? "pin" : "circle",
        symbolSize: m.type === "Entry" ? 26 : m.type === "TP1" ? 14 : 9,
        itemStyle: { color: m.side === "bull" ? "#089981" : "#f23645" },
        label: { show: m.type === "Entry", formatter: m.type, position: "top", color: "#cfd6e4", fontSize: 9 },
      }));
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
      tradeAreas.push([{ xAxis: active.entry_idx, yAxis: active.entry, itemStyle: { color: "rgba(242,54,69,0.10)" } }, { xAxis: end - 1, yAxis: slLevel }]);
      tradeAreas.push([{ xAxis: active.entry_idx, yAxis: active.entry, itemStyle: { color: "rgba(8,153,129,0.10)" } }, { xAxis: end - 1, yAxis: active.tp }]);
    }
    if (toggles.zones) for (const z of data.zones) {
      if (z.price !== undefined)
        markLines.push({ yAxis: z.price, symbol: "none", lineStyle: { color: z.type === "support" ? "#089981" : "#f23645", type: "dotted", opacity: 0.5 }, label: { formatter: z.type === "support" ? "S" : "R", color: "#8a93a6", fontSize: 9 } });
    }
    const zoneAreas = (toggles.zones ? data.zones : [])
      .filter((z) => z.left_idx !== undefined && z.left_idx <= index).slice(-8)
      .map((z) => ([
        { xAxis: z.left_idx, yAxis: z.top, itemStyle: { color: z.type === "demand" ? "rgba(8,153,129,0.12)" : "rgba(242,54,69,0.12)" } },
        { xAxis: end - 1, yAxis: z.bottom },
      ]));

    // ---- price-pane overlay line series (only the toggled-on, computed ones) ----
    const series: any[] = [
      {
        type: "candlestick", data: ohlc, xAxisIndex: 0, yAxisIndex: 0, barMaxWidth: 14,
        itemStyle: { color: "#089981", color0: "#f23645", borderColor: "#089981", borderColor0: "#f23645" },
        markPoint: { data: markPts as any, silent: true },
        markLine: { symbol: "none", data: markLines as any, silent: true },
        markArea: { silent: true, data: [...zoneAreas, ...tradeAreas] as any },
      },
    ];
    const legend: string[] = [];
    const line = (key: string, name: string, color: string, opt: any = {}) => {
      series.push({ type: "line", data: num(ov[key], end), xAxisIndex: 0, yAxisIndex: 0, showSymbol: false,
        smooth: true, lineStyle: { color, width: 1.3, ...(opt.lineStyle || {}) }, name, ...opt });
      legend.push(name);
    };
    if (toggles.ema8) line("ema8", "EMA8", "#22d3ee");
    if (toggles.ema20) line("ema20", "EMA20", "#3b82f6");
    if (toggles.ema30) line("ema30", "EMA30", "#a855f7");
    if (toggles.ema50) line("ema50", "EMA50", "#f59e0b");
    if (toggles.sma20) line("sma20", "SMA20", "#60a5fa", { smooth: false, lineStyle: { width: 1.1, type: "dashed" } });
    if (toggles.sma50) line("sma50", "SMA50", "#fbbf24", { smooth: false, lineStyle: { width: 1.1, type: "dashed" } });
    if (toggles.vwap) line("vwap", "VWAP", "#8b5cf6", { smooth: false, lineStyle: { width: 1.1, type: "dashed" } });
    if (toggles.bb) {
      line("bb_upper", "BB", "#5b6478", { lineStyle: { width: 1, opacity: 0.8 } });
      series.push({ type: "line", data: num(ov.bb_mid, end), xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, smooth: true, lineStyle: { color: "#5b6478", width: 0.8, type: "dotted", opacity: 0.7 }, name: "BBmid" });
      series.push({ type: "line", data: num(ov.bb_lower, end), xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, smooth: true, lineStyle: { color: "#5b6478", width: 1, opacity: 0.8 }, name: "BBlo",
        areaStyle: { color: "rgba(91,100,120,0.06)", origin: "start" } });
    }
    if (hasVol) series.push({ type: "bar", data: vol as any, xAxisIndex: volGrid, yAxisIndex: volGrid, barMaxWidth: 14 });

    // ---- oscillator pane ----
    if (toggles.osc === "rsi") {
      series.push({ type: "line", data: num(ov.rsi, end), xAxisIndex: oscGrid, yAxisIndex: oscGrid, showSymbol: false, smooth: true,
        lineStyle: { color: "#8b5cf6", width: 1.2 }, name: "RSI",
        markLine: { symbol: "none", silent: true, data: [
          { yAxis: 70, lineStyle: { color: "#f23645", type: "dashed", opacity: 0.5 }, label: { formatter: "70", color: "#8a93a6", fontSize: 9 } },
          { yAxis: 30, lineStyle: { color: "#089981", type: "dashed", opacity: 0.5 }, label: { formatter: "30", color: "#8a93a6", fontSize: 9 } },
          { yAxis: 50, lineStyle: { color: "#5b6478", type: "dotted", opacity: 0.4 }, label: { show: false } },
        ] } });
    } else if (toggles.osc === "macd") {
      const hist = num(ov.macd_hist, end).map((v) => v === null ? null : ({ value: v, itemStyle: { color: v >= 0 ? "#089981" : "#f23645" } }));
      series.push({ type: "bar", data: hist as any, xAxisIndex: oscGrid, yAxisIndex: oscGrid, barMaxWidth: 6, name: "Hist" });
      series.push({ type: "line", data: num(ov.macd, end), xAxisIndex: oscGrid, yAxisIndex: oscGrid, showSymbol: false, smooth: true, lineStyle: { color: "#3b82f6", width: 1.2 }, name: "MACD" });
      series.push({ type: "line", data: num(ov.macd_signal, end), xAxisIndex: oscGrid, yAxisIndex: oscGrid, showSymbol: false, smooth: true, lineStyle: { color: "#f59e0b", width: 1.1 }, name: "Signal" });
    } else if (toggles.osc === "atr") {
      series.push({ type: "line", data: num(ov.atr, end), xAxisIndex: oscGrid, yAxisIndex: oscGrid, showSymbol: false, smooth: true, lineStyle: { color: "#22d3ee", width: 1.2 }, name: "ATR", areaStyle: { color: "rgba(34,211,238,0.08)" } });
    }

    const startV = Math.max(0, end - WINDOW);
    const allX = grids.map((_, gi) => gi);
    const option: EChartsOption = {
      backgroundColor: "transparent",
      animation: false,
      title: {
        left: 58, top: 4, textStyle: { color: upCol, fontSize: 11, fontWeight: 500 },
        text: `${data.meta.symbol} ${data.meta.timeframe}   O ${fmt(last.o)}  H ${fmt(last.h)}  L ${fmt(last.l)}  C ${fmt(last.c)}  Vol ${volFmt(last.v)}   ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`,
      },
      axisPointer: { link: [{ xAxisIndex: "all" }], label: { backgroundColor: "#1e2438" } },
      legend: legend.length ? { data: legend, top: 4, right: 64, itemWidth: 14, itemHeight: 8,
        textStyle: { color: "#8a93a6", fontSize: 10 }, icon: "roundRect" } : undefined,
      grid: grids,
      xAxis, yAxis,
      dataZoom: [
        { type: "inside", xAxisIndex: allX, startValue: startV, endValue: end - 1, zoomOnMouseWheel: true, moveOnMouseMove: true, minValueSpan: 20 },
        { type: "slider", xAxisIndex: allX, startValue: startV, endValue: end - 1, height: 18, bottom: 6,
          backgroundColor: "rgba(30,36,56,0.4)", fillerColor: "rgba(139,92,246,0.15)", borderColor: "#2a3350",
          handleStyle: { color: "#8b5cf6" }, textStyle: { color: "#8a93a6", fontSize: 9 }, dataBackground: { lineStyle: { color: "#2a3350" }, areaStyle: { color: "#161d30" } } },
      ],
      tooltip: {
        trigger: "axis", axisPointer: { type: "cross", crossStyle: { color: "#5b6478" } },
        backgroundColor: "rgba(13,18,32,0.96)", borderColor: "#2a3350", textStyle: { color: "#e6eaf2", fontSize: 11 },
        formatter: (ps: any) => {
          const i = ps[0].dataIndex; const b = c[i]; if (!b) return "";
          const up = b.c >= b.o;
          let s = `<b>${cats[i]}</b><br/>O ${fmt(b.o)}  H ${fmt(b.h)}<br/>L ${fmt(b.l)}  <span style="color:${up ? "#089981" : "#f23645"}">C ${fmt(b.c)}</span><br/>Vol ${volFmt(b.v)}`;
          const rsi = ov.rsi?.[i]; const atr = ov.atr?.[i]; const macd = ov.macd?.[i];
          if (toggles.osc === "rsi" && rsi != null) s += `<br/>RSI ${rsi.toFixed(1)}`;
          if (toggles.osc === "atr" && atr != null) s += `<br/>ATR ${fmt(atr)}`;
          if (toggles.osc === "macd" && macd != null) s += `<br/>MACD ${macd.toFixed(2)}`;
          return s;
        },
      },
      series,
    };
    chart.setOption(option, true);
  }, [data, index, toggles, height]);

  return <div ref={elRef} style={{ width: "100%", height }} />;
}
