import { useEffect, useRef, useState } from "react";
import Icon from "../common/Icon";
import { useApp } from "../../app-context";
import { useLive, type AlertRow } from "../../lib/api";

// Unread is tracked client-side (single-user tool): we remember the timestamp of
// the newest alert the user has seen. Opening the panel marks everything current
// as seen, clearing the badge. Persisted so it survives reloads.
const SEEN_KEY = "nexus.alerts.seenTs";
const SEV_DOT: Record<string, string> = { critical: "red", error: "red", warning: "amber", warn: "amber", info: "blue", success: "green" };

function relTime(ts: string): string {
  const d = Date.now() - new Date(ts).getTime();
  if (!isFinite(d)) return "";
  const m = Math.floor(d / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function NotificationBell() {
  const app = useApp();
  const { data } = useLive<AlertRow[]>("/ledger/alerts?limit=25", 12000);
  const [open, setOpen] = useState(false);
  const [seenTs, setSeenTs] = useState<string>(() => localStorage.getItem(SEEN_KEY) ?? "");
  const ref = useRef<HTMLDivElement | null>(null);

  const alerts = data ?? [];
  const unread = alerts.filter((a) => a.ts > seenTs).length;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const markAllRead = () => {
    const newest = alerts.reduce((mx, a) => (a.ts > mx ? a.ts : mx), seenTs);
    setSeenTs(newest); localStorage.setItem(SEEN_KEY, newest);
  };
  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) markAllRead();   // opening the tray counts as reading
  };

  return (
    <div className="notif-wrap" ref={ref}>
      <button className="icon-btn" aria-label={`Notifications${unread ? ` (${unread} unread)` : ""}`} onClick={toggle}>
        <Icon name="bell" size={18} />
        {unread > 0 && <span className="notif-badge">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="hdr-pop hdr-pop-wide notif-pop" role="menu">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <p className="hdr-pop-title" style={{ margin: 0 }}>Notifications</p>
            <button className="chip-btn" onClick={() => { app.go("Alerts"); setOpen(false); }}>View all</button>
          </div>
          {alerts.length === 0 ? (
            <div className="dim" style={{ fontSize: 12.5, padding: "10px 2px" }}>No alerts yet — you're all caught up.</div>
          ) : (
            <div style={{ maxHeight: 360, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
              {alerts.slice(0, 20).map((a) => (
                <div key={a.id} className="notif-item">
                  <span className={`dot ${SEV_DOT[a.severity] ?? "blue"}`} style={{ marginTop: 5, flex: "none" }} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                      <b style={{ fontSize: 12.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{a.title}</b>
                      <span className="dim" style={{ fontSize: 10.5, marginLeft: "auto", whiteSpace: "nowrap" }}>{relTime(a.ts)}</span>
                    </div>
                    {a.detail && <div className="dim" style={{ fontSize: 11.5, lineHeight: 1.4 }}>{a.detail}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
