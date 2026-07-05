import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { useLive, hhmmss, API_BASE } from "../lib/api";

/** Bot Health — one honest operational view of the running bot. Every field is
 *  real (from the engine, ledger, watchdog and skip log); nothing is faked. */

type BotHealth = {
  engine: {
    running: boolean; mode: string | null; strategy: string; symbols: string[];
    timeframe: string; bars_processed: number; signals: number; trades: number;
    rejections: number; uptime_s: number; started_at: string | null;
  };
  data_source: string;
  broker: { connected: boolean; active: string; live_locked: boolean; note: string };
  last_candle: { symbol: string | null; ts: string | null };
  last_signal: { symbol: string; side: string; entry: number; ts: string } | null;
  last_rejected: { symbol: string; side: string; stage: string; reason: string; ts: string } | null;
  open_positions: number;
  daily_pnl: number;
  risk: {
    equity: number; exposure_pct: number; exposure_limit_pct: number;
    open_positions: number; max_open_positions: number; trading_state: string;
    auto_halted: boolean; halt_reason: string; max_drawdown_pct: number;
  };
  watchdog: { running: boolean; findings?: string[]; last_heartbeat?: string | null; [k: string]: any };
  errors: { ts: string; stage: string; message: string; symbol: string | null }[];
};

const money = (n: number | null | undefined) => `$${(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const ago = (ts: string | null | undefined) => (ts ? hhmmss(ts) : "—");
const uptime = (s: number) => s >= 3600 ? `${(s / 3600).toFixed(1)}h` : s >= 60 ? `${Math.round(s / 60)}m` : `${Math.round(s)}s`;

function Row({ k, v, tone }: { k: string; v: any; tone?: string }) {
  return (
    <div className="risk-item">
      <span className="dim">{k}</span>
      <b style={{ fontSize: 13, color: tone }}>{v ?? "—"}</b>
    </div>
  );
}

export default function BotHealthPage() {
  const h = useLive<BotHealth>("/health/bot", 3000);
  const d = h.data;
  const offline = h.error && !d;

  return (
    <>
      <PageHeader title="Bot Health" subtitle="live operational status — engine, feed, broker, risk, watchdog, errors" />

      {offline && (
        <div className="card" style={{ borderColor: "#ef4444", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="warning" size={16} className="neg" />
          <span><b>Backend not reachable.</b> Start it with <span className="mono">cd automation-hub &amp;&amp; uvicorn app:app</span> (expected at <span className="mono">{API_BASE}</span>).</span>
        </div>
      )}

      <div className="stat-row">
        <StatCard label="Engine" value={d?.engine.running ? "Running" : "Stopped"} tone={d?.engine.running ? "green" : "red"}
          sub={d ? `${d.engine.strategy} · ${d.engine.timeframe}` : ""} />
        <StatCard label="Data Source" value={d?.data_source ?? "—"} sub={d ? `${d.engine.symbols.length} symbols` : ""} />
        <StatCard label="Broker" value={d?.broker.connected ? "Connected" : "Paper only"} tone={d?.broker.connected ? "green" : "amber"}
          sub={d?.broker.live_locked ? "live locked" : ""} />
        <StatCard label="Today's P&L" value={money(d?.daily_pnl)} tone={(d?.daily_pnl ?? 0) >= 0 ? "green" : "red"}
          sub={`${d?.open_positions ?? 0} open`} />
        <StatCard label="Trading State" value={d?.risk.trading_state ?? "—"}
          tone={d?.risk.trading_state === "Active" ? "green" : d?.risk.trading_state === "Paused" ? "amber" : "red"} />
      </div>

      {d?.risk.auto_halted && (
        <div className="card" style={{ borderColor: "#ef4444", background: "rgba(239,68,68,0.08)", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="warning" size={16} className="neg" />
          <span><b className="neg">Auto-halted.</b> <span className="dim">{d.risk.halt_reason || "a safety circuit breaker tripped"}</span></span>
        </div>
      )}

      <div className="grid-2-eq">
        <Card title="Engine" subtitle="the running strategy loop" right={d && <Badge text={d.engine.running ? "up" : "down"} tone={d.engine.running ? "green" : "red"} />}>
          {d && (
            <div className="risk-list">
              <Row k="Mode" v={d.engine.mode ?? "paper"} />
              <Row k="Strategy" v={d.engine.strategy} />
              <Row k="Symbols" v={d.engine.symbols.join(", ")} />
              <Row k="Timeframe" v={d.engine.timeframe} />
              <Row k="Bars processed" v={d.engine.bars_processed.toLocaleString()} />
              <Row k="Signals" v={d.engine.signals} />
              <Row k="Trades" v={d.engine.trades} />
              <Row k="Rejections" v={d.engine.rejections} />
              <Row k="Uptime" v={uptime(d.engine.uptime_s)} />
              <Row k="Started" v={ago(d.engine.started_at)} />
            </div>
          )}
        </Card>

        <Card title="Feed & Signals" subtitle="last candle, last signal, last rejection">
          {d && (
            <div className="risk-list">
              <Row k="Data source" v={d.data_source} />
              <Row k="Last candle" v={`${d.last_candle.symbol ?? "—"} · ${ago(d.last_candle.ts)}`} />
              <Row k="Last signal" v={d.last_signal ? `${d.last_signal.symbol} ${d.last_signal.side} @ ${d.last_signal.entry} · ${ago(d.last_signal.ts)}` : "none yet"} />
              <div className="risk-item" style={{ alignItems: "flex-start", flexDirection: "column", gap: 2 }}>
                <span className="dim">Last rejected signal</span>
                {d.last_rejected ? (
                  <span style={{ fontSize: 12 }}>
                    <b>{d.last_rejected.symbol} {d.last_rejected.side}</b>{" "}
                    <Badge text={d.last_rejected.stage} tone="amber" />{" "}
                    <span className="dim">{d.last_rejected.reason} · {ago(d.last_rejected.ts)}</span>
                  </span>
                ) : <b style={{ fontSize: 13 }}>none yet</b>}
              </div>
            </div>
          )}
        </Card>

        <Card title="Risk" subtitle="live usage vs limits">
          {d && (
            <div className="risk-list">
              <Row k="Equity" v={money(d.risk.equity)} />
              <Row k="Exposure" v={`${(d.risk.exposure_pct * 100).toFixed(1)}% / ${(d.risk.exposure_limit_pct * 100).toFixed(0)}%`} />
              <Row k="Open positions" v={`${d.risk.open_positions} / ${d.risk.max_open_positions}`} />
              <Row k="Max drawdown" v={`${(d.risk.max_drawdown_pct * 100).toFixed(0)}%`} />
              <Row k="Auto-halted" v={d.risk.auto_halted ? "YES" : "no"} tone={d.risk.auto_halted ? "#ef4444" : undefined} />
            </div>
          )}
        </Card>

        <Card title="Watchdog" subtitle="feed / thread / websocket heartbeat"
          right={d && <Badge text={d.watchdog.running ? "running" : "down"} tone={d.watchdog.running ? "green" : "red"} />}>
          {d && (
            <div className="risk-list">
              <Row k="Running" v={d.watchdog.running ? "yes" : "no"} tone={d.watchdog.running ? undefined : "#ef4444"} />
              <Row k="Last heartbeat" v={ago(d.watchdog.last_heartbeat)} />
              <div className="risk-item" style={{ alignItems: "flex-start", flexDirection: "column", gap: 2 }}>
                <span className="dim">Findings</span>
                {(d.watchdog.findings?.length ?? 0) === 0
                  ? <b style={{ fontSize: 13 }} className="pos">all clear</b>
                  : <ul style={{ margin: "2px 0 0", paddingLeft: 16 }} className="neg">{d.watchdog.findings!.map((f, i) => <li key={i} style={{ fontSize: 12 }}>{f}</li>)}</ul>}
              </div>
            </div>
          )}
        </Card>
      </div>

      <Card title="Latest Errors" subtitle="most recent error / critical log lines"
        right={d && <Badge text={`${d.errors.length}`} tone={d.errors.length ? "red" : "green"} />}>
        {d && d.errors.length === 0 ? (
          <div className="dim" style={{ fontSize: 13 }}><Icon name="check" size={13} className="pos" /> No errors logged.</div>
        ) : (
          <div className="tablewrap">
            <table className="data-table">
              <thead><tr><th>Time</th><th>Stage</th><th>Symbol</th><th>Message</th></tr></thead>
              <tbody>
                {d?.errors.map((e, i) => (
                  <tr key={i}>
                    <td className="dim mono">{ago(e.ts)}</td>
                    <td><Badge text={e.stage} tone="red" /></td>
                    <td>{e.symbol ?? "—"}</td>
                    <td>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
