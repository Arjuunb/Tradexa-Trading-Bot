import { useLive, uptime, type SystemStatus } from "../../lib/api";

// Footer = real system-health bar (no fake prices). Reflects the live backend.
export default function TickerBar() {
  const { data } = useLive<SystemStatus>("/system/status", 4000);

  // A bare "Bars 0" is ambiguous: on a 4h timeframe a freshly started engine
  // and one whose feed died nine hours ago look identical. The backend already
  // decides which (the same verdict the diagnostics page shows), so annotate
  // the count with it rather than leaving the reader to guess.
  const bars = data
    ? (data.bars_processed === 0 && data.bars_note
        ? `0 — ${data.bars_note.replace(/\.$/, "")}`
        : String(data.bars_processed))
    : "";

  const items: [string, string, string?][] = data
    ? [
        ["Mode", "PAPER (simulation)"],
        ["Data", data.data_source],
        ["Broker", data.broker_connected ? "connected" : "not connected"],
        ["Strategy", `${data.strategy} · ${data.timeframe}`],
        ["Engine", data.engine_running ? `running (${data.engine_mode})` : "stopped"],
        ["Bars", bars, data.bars_processed === 0 ? data.bars_severity : undefined],
        ["Uptime", uptime(data.uptime_s)],
      ]
    : [["System", "backend not reachable"]];

  const tone = (sev?: string) =>
    sev === "critical" ? "var(--red, #f23645)"
      : sev === "warning" ? "var(--amber, #eab54f)"
        : undefined;

  return (
    <footer className="ticker">
      <div className="ticker-items">
        {items.map(([k, v, sev]) => (
          <span className="ticker-item" key={k}>
            <b>{k}</b>
            <span className="ticker-price" style={{ color: tone(sev) }}
                  title={sev ? "From engine diagnostics" : undefined}>{v}</span>
          </span>
        ))}
      </div>
      <div className="ticker-meta">
        <span className={`dot ${data?.engine_running ? "online" : "offline"}`} />
      </div>
    </footer>
  );
}
