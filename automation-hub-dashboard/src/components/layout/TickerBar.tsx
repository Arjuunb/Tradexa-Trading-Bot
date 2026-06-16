import { useLive, uptime, type SystemStatus } from "../../lib/api";

// Footer = real system-health bar (no fake prices). Reflects the live backend.
export default function TickerBar() {
  const { data } = useLive<SystemStatus>("/system/status", 4000);

  const items: [string, string][] = data
    ? [
        ["Mode", "PAPER (simulation)"],
        ["Data", data.data_source],
        ["Broker", data.broker_connected ? "connected" : "not connected"],
        ["Strategy", `${data.strategy} · ${data.timeframe}`],
        ["Engine", data.engine_running ? `running (${data.engine_mode})` : "stopped"],
        ["Bars", String(data.bars_processed)],
        ["Uptime", uptime(data.uptime_s)],
      ]
    : [["System", "backend not reachable"]];

  return (
    <footer className="ticker">
      <div className="ticker-items">
        {items.map(([k, v]) => (
          <span className="ticker-item" key={k}>
            <b>{k}</b>
            <span className="ticker-price">{v}</span>
          </span>
        ))}
      </div>
      <div className="ticker-meta">
        <span className={`dot ${data?.engine_running ? "online" : "offline"}`} />
      </div>
    </footer>
  );
}
