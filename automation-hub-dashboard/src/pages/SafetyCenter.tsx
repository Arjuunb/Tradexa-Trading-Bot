import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { PageHeader } from "../components/common/ui";
import { useApp } from "../app-context";
import { apiPost, useLive, type PaperTradeRow, type SystemStatus } from "../lib/api";
import { getProgress } from "../lib/progress";

const STAGES = ["Backtest", "Simulation", "Paper Trading", "Live Trading"];

export default function SafetyCenterPage() {
  const app = useApp();
  const sys = useLive<SystemStatus>("/system/status", 3000);
  const trades = useLive<PaperTradeRow[]>("/paper/trades", 4000);
  const prog = getProgress();

  const done = [
    prog.backtest,
    prog.simulation,
    (trades.data?.length ?? 0) > 0,
    !!sys.data?.broker_connected,
  ];

  const killAll = async () => {
    if (!window.confirm("KILL SWITCH: immediately halt all trading and stop the engine?")) return;
    try {
      await apiPost("/controls/stop-all");
      await apiPost("/engine/stop");
      app.toast("All trading halted", "error");
      sys.refetch();
    } catch {
      app.toast("Backend not reachable", "error");
    }
  };

  return (
    <>
      <PageHeader title="Safety Center" subtitle="Progression flow, data separation and emergency controls" />

      <Card title="Required Progression" subtitle="strategies can never skip a step">
        <div className="flow-row" style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          {STAGES.map((name, i) => (
            <span key={name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="ui-badge" style={{ background: done[i] ? "#22c55e22" : "#5b647822", color: done[i] ? "#22c55e" : "#8a93a6", display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Icon name={done[i] ? "check" : "lock"} size={13} /> {name}
              </span>
              {i < STAGES.length - 1 && <Icon name="chevron" size={14} className="dim" />}
            </span>
          ))}
        </div>
        <p className="dim" style={{ marginTop: 10 }}>
          Live stays locked until every earlier stage has real, recorded results and a broker is connected.
        </p>
      </Card>

      <Card title="Data Separation" subtitle="datasets are never mixed or cross-shown">
        <div className="risk-list">
          <div className="risk-item"><b>Backtest</b> <span className="dim">— historical, on the Backtesting page.</span></div>
          <div className="risk-item"><b>Simulation</b> <span className="dim">— forward sim, on the Simulation page.</span></div>
          <div className="risk-item"><b>Paper</b> <span className="dim">— real engine, simulated money, on the Paper Trading page.</span></div>
          <div className="risk-item"><b>Live</b> <span className="dim">— locked; no live data exists until a broker is connected.</span></div>
        </div>
        <p className="dim" style={{ marginTop: 8 }}>Simulated and paper performance are always labelled as such — never shown as live results.</p>
      </Card>

      <Card title="Emergency Controls">
        <div className="estop-box">
          <div><b className="neg">Kill Switch</b><span className="dim">Immediately halt all trading and stop the engine (paper).</span></div>
          <button className="btn btn-danger" onClick={killAll}><Icon name="close" size={14} /> Stop Everything</button>
        </div>
      </Card>
    </>
  );
}
