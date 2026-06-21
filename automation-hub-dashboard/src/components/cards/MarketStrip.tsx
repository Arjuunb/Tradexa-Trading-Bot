import Card from "../common/Card";
import Icon from "../common/Icon";
import Sparkline from "../chart/Sparkline";
import { Badge } from "../common/ui";
import { useLive, type SystemStatus, type Watchlist } from "../../lib/api";

const fmt = (n?: number) => (n == null ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: n >= 100 ? 2 : 4 }));

/** Compact live markets strip for the Overview — real Binance quotes from the
 *  cached candle store (honest "no data" until synced). */
export default function MarketStrip() {
  const { data: sys } = useLive<SystemStatus>("/system/status", 4000);
  const syms = sys?.symbols?.length ? sys.symbols.join(",") : "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT";
  const watch = useLive<Watchlist>(`/markets/watchlist?symbols=${syms}&timeframe=1d`, 20000);
  const rows = watch.data?.symbols ?? [];

  return (
    <Card title="Markets" subtitle="tracked symbols · 1d change from real Binance candles">
      <div className="watch-grid">
        {rows.map((w) => {
          const up = (w.change_pct ?? 0) >= 0;
          return (
            <div className="watch-card" key={w.symbol} style={{ ["--wc-accent" as any]: w.available ? (up ? "var(--green)" : "var(--red)") : "var(--dim-2)" }}>
              <div className="watch-top">
                <div className="watch-sym">
                  <span className="watch-avatar">{w.symbol.replace("USDT", "").slice(0, 3)}</span>
                  <b>{w.symbol.replace("USDT", "")}</b>
                </div>
                {w.available
                  ? <Badge text={`${up ? "+" : ""}${w.change_pct}%`} tone={up ? "green" : "red"} />
                  : <Badge text="no data" tone="default" />}
              </div>
              {w.available ? (
                <>
                  <div className="watch-price" style={{ fontSize: 20 }}>{fmt(w.last)}</div>
                  <div className="watch-spark"><Sparkline data={w.spark ?? []} color={up ? "#22c55e" : "#ef4444"} height={36} /></div>
                  <span className="dim" style={{ fontSize: 11 }}>Volatility {w.vol_pct}%</span>
                </>
              ) : (
                <span className="dim" style={{ fontSize: 12, padding: "8px 0" }}><Icon name="info" size={12} /> Sync candles on Replay</span>
              )}
            </div>
          );
        })}
        {rows.length === 0 && <div className="dim ta-center" style={{ gridColumn: "1/-1", padding: 16 }}>Loading quotes…</div>}
      </div>
    </Card>
  );
}
