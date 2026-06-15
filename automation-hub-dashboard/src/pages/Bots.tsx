import { useMemo, useState } from "react";
import type { Bot, BotStatus } from "../types";
import Icon from "../components/common/Icon";
import Modal from "../components/common/Modal";
import { PageHeader, StatusBadge } from "../components/common/ui";
import { useApp } from "../app-context";

interface BotsPageProps {
  bots: Bot[];
  setBots: React.Dispatch<React.SetStateAction<Bot[]>>;
  onCreate: () => void;
}

const STATUSES: (BotStatus | "All")[] = ["All", "Running", "Live", "Paper", "Paused", "Stopped"];

function money(n: number) {
  if (n === 0) return "$0.00";
  return `${n > 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`;
}

export default function BotsPage({ bots, setBots, onCreate }: BotsPageProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<BotStatus | "All">("All");
  const [modalBot, setModalBot] = useState<Bot | null>(null);
  const app = useApp();

  const visible = useMemo(
    () =>
      bots.filter(
        (b) =>
          (filter === "All" || b.status === filter) &&
          (b.name.toLowerCase().includes(query.toLowerCase()) ||
            b.pair.toLowerCase().includes(query.toLowerCase()) ||
            b.strategy.toLowerCase().includes(query.toLowerCase())),
      ),
    [bots, query, filter],
  );

  const setStatus = (id: string, status: BotStatus) =>
    setBots((prev) => prev.map((b) => (b.id === id ? { ...b, status } : b)));
  const remove = (id: string) => setBots((prev) => prev.filter((b) => b.id !== id));
  const duplicate = (id: string) =>
    setBots((prev) => {
      const src = prev.find((b) => b.id === id);
      if (!src) return prev;
      return [
        ...prev,
        { ...src, id: "b" + Math.random().toString(36).slice(2, 7), name: `${src.name} (copy)`, status: "Stopped", todayPnl: 0 },
      ];
    });

  return (
    <>
      <PageHeader
        title="Bots"
        subtitle={`${bots.length} bots · ${bots.filter((b) => b.status === "Running" || b.status === "Live").length} active`}
        actions={
          <button className="btn btn-primary" onClick={onCreate}>
            <Icon name="plus" size={15} /> Create Bot
          </button>
        }
      />

      <div className="toolbar">
        <div className="search">
          <Icon name="info" size={15} className="search-icon" />
          <input placeholder="Search bots, symbols, strategies…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="chips">
          {STATUSES.map((s) => (
            <button key={s} className={`chip-btn ${filter === s ? "active" : ""}`} onClick={() => setFilter(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="tablewrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Bot</th><th>Strategy</th><th>Symbol</th><th>TF</th>
                <th>Risk</th><th>Today P&amp;L</th><th>Total P&amp;L</th><th>Status</th>
                <th className="ta-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((b) => {
                const active = b.status === "Running" || b.status === "Live";
                return (
                  <tr key={b.id}>
                    <td><b>{b.name}</b></td>
                    <td className="dim">{b.strategy}</td>
                    <td>{b.pair}</td>
                    <td className="dim">{b.timeframe}</td>
                    <td className="dim">{b.riskPct}%</td>
                    <td className={b.todayPnl >= 0 ? "pos" : "neg"}>{money(b.todayPnl)}</td>
                    <td className={b.totalPnl >= 0 ? "pos" : "neg"}>{money(b.totalPnl)}</td>
                    <td><StatusBadge status={b.status} /></td>
                    <td>
                      <div className="row-actions">
                        {active ? (
                          <button className="icon-btn sm warn" title="Pause" onClick={() => setStatus(b.id, "Paused")}><Icon name="pause" size={14} /></button>
                        ) : (
                          <button className="icon-btn sm ok" title="Start" onClick={() => setStatus(b.id, "Running")}><Icon name="play" size={14} /></button>
                        )}
                        <button className="icon-btn sm" title="Stop" onClick={() => setStatus(b.id, "Stopped")}><Icon name="close" size={14} /></button>
                        <button className="icon-btn sm" title="Edit" onClick={() => setModalBot(b)}><Icon name="settings" size={14} /></button>
                        <button className="icon-btn sm" title="Duplicate" onClick={() => duplicate(b.id)}><Icon name="layers" size={14} /></button>
                        <button className="icon-btn sm" title="View details" onClick={() => app.go("Analytics")}><Icon name="chart" size={14} /></button>
                        <button className="icon-btn sm neg" title="Delete" onClick={() => remove(b.id)}><Icon name="close" size={14} /></button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {visible.length === 0 && (
                <tr><td colSpan={9} className="dim ta-center" style={{ padding: 24 }}>No bots match your filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Modal open={!!modalBot} title={modalBot ? modalBot.name : ""} onClose={() => setModalBot(null)}>
        {modalBot && (
          <div className="detail-grid">
            <div><span className="dim">Strategy</span><b>{modalBot.strategy}</b></div>
            <div><span className="dim">Symbol</span><b>{modalBot.pair}</b></div>
            <div><span className="dim">Timeframe</span><b>{modalBot.timeframe}</b></div>
            <div><span className="dim">Risk / trade</span><b>{modalBot.riskPct}%</b></div>
            <div><span className="dim">Today P&amp;L</span><b className={modalBot.todayPnl >= 0 ? "pos" : "neg"}>{money(modalBot.todayPnl)}</b></div>
            <div><span className="dim">Total P&amp;L</span><b className={modalBot.totalPnl >= 0 ? "pos" : "neg"}>{money(modalBot.totalPnl)}</b></div>
          </div>
        )}
        <p className="dim" style={{ marginTop: 14 }}>Full bot editing connects to the Automation Hub API in a later phase.</p>
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={() => setModalBot(null)}>Close</button>
        </div>
      </Modal>
    </>
  );
}
