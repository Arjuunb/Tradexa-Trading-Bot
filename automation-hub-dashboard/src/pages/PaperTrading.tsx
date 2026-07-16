import { Fragment, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import DecisionJournalPanel from "../components/journal/DecisionJournalPanel";
import ModeApprovals from "../components/trading/ModeApprovals";
import { useApp } from "../app-context";
import {
  apiPost, useLive, hhmmss, API_BASE,
  type AlertRow, type ControlState, type EngineStatus, type LedgerPosition,
  type LogRow, type PaperAccount, type PaperTradeRow,
} from "../lib/api";

const money = (n: number | null | undefined) => `$${(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const stateTone = (s?: string) => (s === "Active" ? "green" : s === "Paused" ? "amber" : "red");
const levelTone = (l: string) => ({ info: "blue", warning: "amber", error: "red" }[l] as any) ?? "default";

export default function PaperTradingPage() {
  const app = useApp();
  const account = useLive<PaperAccount>("/paper/account", 2000);
  const positions = useLive<LedgerPosition[]>("/paper/positions", 2000);
  const trades = useLive<PaperTradeRow[]>("/paper/trades", 2500);
  const control = useLive<ControlState>("/controls/state", 2000);
  const engine = useLive<EngineStatus>("/engine/status", 2000);
  const logs = useLive<LogRow[]>("/ledger/logs?limit=40", 2500);
  const alertsFeed = useLive<AlertRow[]>("/ledger/alerts?limit=20", 4000);

  const offline = account.error && !account.data;
  const [openJournal, setOpenJournal] = useState<string | null>(null);

  const act = async (path: string, msg: string, refetch: () => void) => {
    try {
      await apiPost(path);
      app.toast(msg, "success");
      refetch();
      control.refetch();
      engine.refetch();
    } catch {
      app.toast("Backend not reachable — is the API running?", "error");
    }
  };

  // H-6: destructive controls confirm first (matches Safety Center + resets).
  const confirmAct = (msg: string, path: string, toastMsg: string, refetch: () => void) => {
    if (window.confirm(msg)) void act(path, toastMsg, refetch);
  };

  const eng = engine.data;
  const acct = account.data;
  const state = control.data?.state;

  return (
    <>
      <PageHeader
        title="Paper Trading"
        subtitle="Live engine · real strategy signals → risk → paper execution · no real funds"
        actions={
          <div className="row-actions">
            {eng?.running ? (
              <button className="btn btn-warn" onClick={() => confirmAct("Stop the trading engine? No new signals will be processed until you start it again.", "/engine/stop", "Engine stopped", engine.refetch)}><Icon name="pause" size={14} /> Stop Engine</button>
            ) : (
              <button className="btn btn-primary" onClick={() => act("/engine/start", "Engine started", engine.refetch)}><Icon name="play" size={14} /> Start Engine</button>
            )}
          </div>
        }
      />

      {offline && (
        <div className="card" style={{ borderColor: "#ef4444", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="warning" size={16} className="neg" />
          <span>
            <b>Backend not reachable.</b> Start it with{" "}
            <span className="mono">cd automation-hub &amp;&amp; uvicorn app:app</span>{" "}
            (expected at <span className="mono">{API_BASE}</span>). The autonomous engine then streams real trades here.
          </span>
        </div>
      )}

      {acct?.persistent === false && acct?.warning && (
        <div className="card" style={{ borderColor: "var(--gold)", background: "rgba(234,181,79,0.08)", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="warning" size={16} className="amber" />
          <span><b className="amber">Data not persistent.</b> <span className="dim">{acct.warning}</span></span>
        </div>
      )}

      <div className="stat-row">
        <StatCard label="Current Equity" value={money(acct?.current_equity)} sub={`Initial ${money(acct?.initial_capital)}`} tone={(acct?.current_equity ?? 0) >= (acct?.initial_capital ?? 0) ? "green" : "red"} />
        <StatCard label="Available Balance" value={money(acct?.available_balance)} sub={acct?.fees_paid ? `Realized ${money(acct?.realized_pnl)} · fees ${money(acct.fees_paid)}` : `Realized ${money(acct?.realized_pnl)}`} />
        <StatCard label="Open Positions" value={String(acct?.open_positions ?? 0)} />
        <StatCard label="Engine" value={eng?.running ? "Running" : "Stopped"} tone={eng?.running ? "green" : "red"} sub={eng ? `${eng.signals} signals · ${eng.trades} fills` : ""} />
        <StatCard label="Trading State" value={state ?? "—"} tone={stateTone(state)} />
      </div>

      <Card title="Engine & Emergency Controls" subtitle={eng ? `${eng.symbols.join(", ")} · ${eng.timeframe} · ${eng.bars} bars processed` : "autonomous strategy engine"}>
        <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-warn" onClick={() => confirmAct("Pause all trading? New entries from the engine and webhooks will be blocked until you resume.", "/controls/pause-all", "Trading paused — entries blocked", control.refetch)}><Icon name="pause" size={14} /> Pause All</button>
          <button className="btn btn-danger" onClick={() => confirmAct("Stop all trading? This is a hard halt — resume to re-enable.", "/controls/stop-all", "Trading stopped", control.refetch)}><Icon name="close" size={14} /> Stop All</button>
          <button className="btn btn-primary" onClick={() => act("/controls/resume", "Trading resumed", control.refetch)}><Icon name="play" size={14} /> Resume</button>
        </div>
        {state && state !== "Active" && (
          <p className="dim" style={{ marginTop: 10 }}>
            <b>Trading {state}.</b> New entries from the engine and webhooks are blocked. Paper mode only.
          </p>
        )}
      </Card>

      <ModeApprovals />

      <Card title="Open Positions">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Symbol</th><th>Side</th><th>Size</th><th>Entry</th><th>Stop</th><th>Opened</th></tr></thead>
            <tbody>
              {(positions.data ?? []).map((p) => (
                <tr key={p.id}>
                  <td><b>{p.symbol}</b></td>
                  <td><Badge text={p.side} tone={p.side === "long" ? "green" : "red"} /></td>
                  <td>{p.size.toFixed(6)}</td>
                  <td>{p.entry.toLocaleString()}</td>
                  <td className="dim">{p.stop !== null ? p.stop.toLocaleString() : "—"}</td>
                  <td className="dim mono">{hhmmss(p.opened_at)}</td>
                </tr>
              ))}
              {(positions.data?.length ?? 0) === 0 && <tr><td colSpan={6} className="dim ta-center" style={{ padding: 18 }}>No open positions.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Paper Trade History" subtitle={`${trades.data?.length ?? 0} closed trades`}>
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Symbol</th><th>Side</th><th>Size</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>R:R</th><th>Closed</th><th>Journal</th></tr></thead>
            <tbody>
              {(trades.data ?? []).map((t) => {
                const isOpen = openJournal === String(t.id);
                return (
                <Fragment key={t.id}>
                <tr>
                  <td><b>{t.symbol}</b></td>
                  <td><Badge text={t.side} tone={t.side === "long" ? "green" : "red"} /></td>
                  <td>{t.size.toFixed(6)}</td>
                  <td>{t.entry.toLocaleString()}</td>
                  <td>{t.exit !== null ? t.exit.toLocaleString() : "—"}</td>
                  <td className={(t.pnl ?? 0) >= 0 ? "pos" : "neg"}>{(t.pnl ?? 0) >= 0 ? "+" : ""}{money(t.pnl)}</td>
                  <td>{t.rr !== null ? `${t.rr.toFixed(2)}R` : "—"}</td>
                  <td className="dim mono">{hhmmss(t.closed_at)}</td>
                  <td>
                    <button
                      className="btn btn-ghost btn-sm"
                      aria-expanded={isOpen}
                      onClick={() => setOpenJournal(isOpen ? null : String(t.id))}
                    >
                      <Icon name="chevron" size={12} className={isOpen ? "rot-180" : undefined} />
                      {isOpen ? "Hide" : "View Decision Journal"}
                    </button>
                  </td>
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={9} style={{ background: "var(--surface-2, #121214)", padding: 0 }}>
                      <DecisionJournalPanel tradeId={String(t.id)} />
                    </td>
                  </tr>
                )}
                </Fragment>
                );
              })}
              {(trades.data?.length ?? 0) === 0 && <tr><td colSpan={9} className="dim ta-center" style={{ padding: 18 }}>No closed trades yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid-2-1">
        <Card title="Decision Log" subtitle="every signal explained — passed / rejected + reason" className="span-2">
          <div className="tablewrap">
            <table className="data-table">
              <thead><tr><th>Time</th><th>Level</th><th>Stage</th><th>Symbol</th><th>Message</th></tr></thead>
              <tbody>
                {(logs.data ?? []).map((l) => (
                  <tr key={l.id}>
                    <td className="dim mono">{hhmmss(l.ts)}</td>
                    <td><Badge text={l.level} tone={levelTone(l.level)} /></td>
                    <td className="dim">{l.stage}</td>
                    <td>{l.symbol}</td>
                    <td>{l.message}</td>
                  </tr>
                ))}
                {(logs.data?.length ?? 0) === 0 && <tr><td colSpan={5} className="dim ta-center" style={{ padding: 18 }}>No decisions yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Recent Alerts">
          <div className="alert-stack">
            {(alertsFeed.data ?? []).slice(0, 8).map((a) => (
              <div className="exec-line" key={a.id}>
                <span className="exec-time">{hhmmss(a.ts)}</span> <b>{a.title}</b> <span className="dim">{a.detail}</span>
              </div>
            ))}
            {(alertsFeed.data?.length ?? 0) === 0 && <div className="dim">No alerts yet.</div>}
          </div>
        </Card>
      </div>
    </>
  );
}
