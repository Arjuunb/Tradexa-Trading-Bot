import { useState } from "react";
import type { Strategy } from "../types";
import Icon from "../components/common/Icon";
import Modal from "../components/common/Modal";
import Sparkline from "../components/chart/Sparkline";
import { Badge, PageHeader } from "../components/common/ui";
import { strategies } from "../data/mock";
import { useApp } from "../app-context";

const riskTone = (r: string): "green" | "amber" | "red" =>
  r === "Low" ? "green" : r === "Medium" ? "amber" : "red";

export default function StrategiesPage() {
  const [modal, setModal] = useState<{ s: Strategy; mode: string } | null>(null);
  const app = useApp();

  return (
    <>
      <PageHeader
        title="Strategies"
        subtitle={`${strategies.length} strategies in your library`}
        actions={<button className="btn btn-primary" onClick={() => app.toast("Strategy builder coming soon", "info")}><Icon name="plus" size={15} /> Create Strategy</button>}
      />

      <div className="strategy-grid">
        {strategies.map((s) => (
          <div className="card strategy-card" key={s.id}>
            <div className="strategy-head">
              <div className="strategy-avatar" style={{ background: `${s.color}22`, color: s.color }}>
                <Icon name="layers" size={18} />
              </div>
              <div className="strategy-title">
                <b>{s.name}</b>
                <span className="dim">{s.desc}</span>
              </div>
              <Badge text={`${s.risk} risk`} tone={riskTone(s.risk)} />
            </div>

            <div className="strategy-spark"><Sparkline data={s.spark} color={s.color} height={48} /></div>

            <div className="strategy-stats">
              <div><span className="dim">Win rate</span><b className="pos">{s.winRate}%</b></div>
              <div><span className="dim">Profit factor</span><b>{s.profitFactor}</b></div>
              <div><span className="dim">Avg R:R</span><b>{s.avgRR}</b></div>
              <div><span className="dim">Backtests</span><b>{s.backtests}</b></div>
              <div><span className="dim">Last used</span><b>{s.lastUsed}</b></div>
            </div>

            <div className="strategy-actions">
              <button className="btn btn-ghost sm" onClick={() => setModal({ s, mode: "Rules" })}>View Rules</button>
              <button className="btn btn-ghost sm" onClick={() => setModal({ s, mode: "Edit" })}>Edit</button>
              <button className="btn btn-soft sm" onClick={() => app.backtest(s.name)}>Backtest</button>
            </div>
          </div>
        ))}
      </div>

      <Modal open={!!modal} title={modal ? `${modal.s.name} — ${modal.mode}` : ""} onClose={() => setModal(null)}>
        {modal?.mode === "Rules" && (
          <ul className="rules-list">
            <li>Entry: signal confirmed on the {modal.s.name.split(" ")[0]} condition.</li>
            <li>Stop-loss: ATR-based, {modal.s.avgRR}R target.</li>
            <li>Risk: {modal.s.risk}. Skip trade if daily loss limit hit.</li>
          </ul>
        )}
        {modal?.mode === "Edit" && <p className="dim">Strategy parameter editing connects to the engine in a later phase.</p>}
        {modal?.mode === "Backtest" && <p className="dim">Use the Backtesting page to run a full backtest of {modal.s.name}.</p>}
        <div className="modal-actions"><button className="btn btn-ghost" onClick={() => setModal(null)}>Close</button></div>
      </Modal>
    </>
  );
}
