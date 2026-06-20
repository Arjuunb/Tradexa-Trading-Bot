import { useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import Sparkline from "../components/chart/Sparkline";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { useLive, hhmmss, type LedgerPosition, type SystemStatus, type Watchlist } from "../lib/api";

const TFS = ["1d", "4h", "1h"] as const;
const fmt = (n?: number) => (n == null ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: n >= 100 ? 2 : 4 }));

export default function MarketsPage() {
  const { data: sys } = useLive<SystemStatus>("/system/status", 3000);
  const { data: positions } = useLive<LedgerPosition[]>("/paper/positions", 3000);
  const [tf, setTf] = useState<(typeof TFS)[number]>("1d");

  const symbols = sys?.symbols ?? [];
  const symParam = symbols.length ? symbols.join(",") : "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT";
  const watch = useLive<Watchlist>(`/markets/watchlist?symbols=${symParam}&timeframe=${tf}`, 15000);
  const posBySym = new Map((positions ?? []).map((p) => [p.symbol, p]));
  const rows = watch.data?.symbols ?? [];
  const anyReal = rows.some((r) => r.available);

  return (
    <>
      <PageHeader title="Markets" subtitle="Symbols the engine tracks · real Binance quotes from the cached candle store" />

      <div className="stat-row">
        <StatCard label="Engine" value={sys?.engine_running ? "Running" : "Stopped"} tone={sys?.engine_running ? "green" : "red"} />
        <StatCard label="Mode" value={(sys?.mode ?? "paper").toUpperCase()} />
        <StatCard label="Tracked Symbols" value={String(symbols.length)} />
        <StatCard label="Open Positions" value={String((positions ?? []).length)} />
      </div>

      <div className="toolbar">
        <div className="chips">
          {TFS.map((t) => (
            <button key={t} className={`chip-btn ${tf === t ? "active" : ""}`} onClick={() => setTf(t)}>{t} change</button>
          ))}
        </div>
      </div>

      <div className="watch-grid">
        {rows.map((w) => {
          const p = posBySym.get(w.symbol);
          const up = (w.change_pct ?? 0) >= 0;
          return (
            <div className="watch-card" key={w.symbol} style={{ ["--wc-accent" as any]: up ? "var(--green)" : "var(--red)" }}>
              <div className="watch-top">
                <div className="watch-sym">
                  <span className="watch-avatar">{w.symbol.replace("USDT", "").slice(0, 3)}</span>
                  <div>
                    <b>{w.symbol.replace("USDT", "")}</b><span className="dim"> /USDT</span>
                    <div style={{ fontSize: 11, marginTop: 2 }}>{p ? <Badge text={`${p.side} open`} tone={p.side === "long" ? "green" : "red"} /> : <span className="dim">no position</span>}</div>
                  </div>
                </div>
                {w.available
                  ? <Badge text={`${up ? "+" : ""}${w.change_pct}%`} tone={up ? "green" : "red"} />
                  : <Badge text="no data" tone="default" />}
              </div>

              {w.available ? (
                <>
                  <div className="watch-price">{fmt(w.last)}</div>
                  <div className="watch-spark">
                    <Sparkline data={w.spark ?? []} color={up ? "#22c55e" : "#ef4444"} height={44} />
                  </div>
                  <div className="watch-foot">
                    <span><span className="dim">Volatility</span> <b>{w.vol_pct}%</b></span>
                    {p && <span><span className="dim">Entry</span> <b>{fmt(p.entry)}</b></span>}
                    {p && <span className="dim mono">{hhmmss(p.opened_at)}</span>}
                  </div>
                </>
              ) : (
                <div className="watch-empty">
                  <Icon name="info" size={14} className="dim" /> No cached candles for {w.symbol} ({tf}).
                  <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>Sync it on Replay or run /data/sync.</div>
                </div>
              )}
            </div>
          );
        })}
        {rows.length === 0 && <div className="dim ta-center" style={{ padding: 24, gridColumn: "1/-1" }}>{watch.loading ? "Loading quotes…" : "No symbols configured."}</div>}
      </div>

      {!anyReal && rows.length > 0 && (
        <Card title="">
          <p className="dim" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Icon name="info" size={14} /> No real Binance candles are cached yet — quotes show "no data" rather than faked numbers. Sync history on the Replay page to populate the watchlist.
          </p>
        </Card>
      )}
    </>
  );
}
