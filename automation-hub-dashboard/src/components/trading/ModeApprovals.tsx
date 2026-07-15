import { useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { useApp } from "../../app-context";
import { apiPost, apiPostJson, useLive } from "../../lib/api";

/** Trading Mode & Approvals — §7 (modes) + §11 (approval workflow).
 *  FULL AUTO executes; SEMI-AUTO queues each ENTRY for human approval;
 *  SIGNAL only alerts. Exits always execute automatically in every mode. */

interface Idea {
  id: number; symbol: string; side: string; entry: number; stop: number;
  target: number; confidence: number | null; planned_rr: number | null;
  brain_score: number | null; timeframe: string | null; strategy: string | null;
  reason: string | null; status: string; reject_reason?: string;
}
interface ModeResp { mode: string; modes: string[]; pending_approvals: number }
interface ApprovalsResp { mode: string; pending: Idea[]; recent: Idea[] }

const MODES: { key: string; label: string; desc: string }[] = [
  { key: "full", label: "Full Auto", desc: "The bot executes qualifying setups automatically." },
  { key: "semi", label: "Semi-Auto", desc: "The bot finds setups; you approve each entry." },
  { key: "signal", label: "Signal", desc: "The bot only alerts — no orders are placed." },
];

const money = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: 6 });
const statusTone = (s: string) =>
  s === "approved" ? "green" : s === "rejected" ? "red" : s === "expired" ? "amber" : "default";

function ApprovalCard({ idea, onDone }: { idea: Idea; onDone: () => void }) {
  const app = useApp();
  const [busy, setBusy] = useState(false);
  const buy = idea.side === "BUY";
  const act = async (kind: "approve" | "reject") => {
    setBusy(true);
    try {
      if (kind === "approve") {
        const r = await apiPost<{ result?: { ok?: boolean; reason?: string } }>(`/approvals/${idea.id}/approve`);
        app.toast(r.result?.ok ? `Approved — ${idea.symbol} ${idea.side} executed`
          : `Approved, but the risk pipeline blocked it: ${r.result?.reason ?? "see logs"}`,
          r.result?.ok ? "success" : "error");
      } else {
        await apiPostJson(`/approvals/${idea.id}/reject`, { reason: "manual" });
        app.toast(`Rejected — ${idea.symbol} ${idea.side} passed on`, "info");
      }
      onDone();
    } catch {
      app.toast("Idea no longer available (it may have expired).", "error");
      onDone();
    }
    setBusy(false);
  };
  return (
    <div className="approval-card">
      <div className="approval-head">
        <Badge text={idea.side} tone={buy ? "green" : "red"} />
        <b style={{ fontSize: 15 }}>{idea.symbol}</b>
        <span className="dim">{idea.timeframe} · {idea.strategy}</span>
        {idea.brain_score != null && <span className="dim mono" style={{ marginLeft: "auto" }}>score {idea.brain_score}/100</span>}
      </div>
      <div className="approval-levels">
        <span><span className="dim">Entry </span><b className="mono">{money(idea.entry)}</b></span>
        <span><span className="dim">Stop </span><b className="mono neg">{money(idea.stop)}</b></span>
        <span><span className="dim">Target </span><b className="mono pos">{money(idea.target)}</b></span>
        <span><span className="dim">R:R </span><b>{idea.planned_rr != null ? `${idea.planned_rr}:1` : "—"}</b></span>
        {idea.confidence != null && <span><span className="dim">Conf </span><b>{Math.round(idea.confidence * 100)}%</b></span>}
      </div>
      {idea.reason && <p className="dim" style={{ fontSize: 12.5, margin: "2px 0 0" }}>{idea.reason}</p>}
      <div className="approval-actions">
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void act("approve")}>
          <Icon name="check" size={13} /> Approve
        </button>
        <button className="btn btn-danger btn-sm" disabled={busy} onClick={() => void act("reject")}>
          <Icon name="close" size={13} /> Reject
        </button>
      </div>
    </div>
  );
}

export default function ModeApprovals() {
  const app = useApp();
  const modeState = useLive<ModeResp>("/engine/mode", 4000);
  const approvals = useLive<ApprovalsResp>("/approvals", 3000);
  const [busy, setBusy] = useState(false);
  const mode = modeState.data?.mode ?? "full";
  const pending = approvals.data?.pending ?? [];
  const recent = (approvals.data?.recent ?? []).slice(0, 6);

  const setMode = async (m: string) => {
    if (m === mode) return;
    setBusy(true);
    try {
      await apiPostJson("/engine/mode", { mode: m });
      app.toast(`Trading mode → ${MODES.find((x) => x.key === m)?.label}`, "success");
      modeState.refetch();
    } catch {
      app.toast("Could not change mode — backend unreachable.", "error");
    }
    setBusy(false);
  };

  const refresh = () => { approvals.refetch(); modeState.refetch(); };

  return (
    <Card title="Trading Mode & Approvals"
          subtitle="how the bot acts on the setups it finds · exits always execute automatically">
      <div className="mode-seg">
        {MODES.map((m) => (
          <button key={m.key} type="button" disabled={busy}
                  className={`mode-btn ${mode === m.key ? "active" : ""}`}
                  onClick={() => void setMode(m.key)}>
            <b>{m.label}</b>
            <span className="dim">{m.desc}</span>
          </button>
        ))}
      </div>

      {mode === "semi" && (
        <div style={{ marginTop: 14 }}>
          <p className="section-label">Awaiting approval ({pending.length})</p>
          {pending.length === 0 ? (
            <p className="dim" style={{ fontSize: 13 }}>
              No trade ideas awaiting approval. When the engine finds a qualifying setup it appears here for your decision.
            </p>
          ) : (
            <div className="approval-grid">
              {pending.map((idea) => <ApprovalCard key={idea.id} idea={idea} onDone={refresh} />)}
            </div>
          )}
        </div>
      )}

      {mode === "signal" && (
        <p className="dim" style={{ marginTop: 12, fontSize: 13 }}>
          Signal mode: the engine records every setup as an alert below but never places an order. Switch to Semi-Auto to approve entries, or Full Auto to execute automatically.
        </p>
      )}

      {recent.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <p className="section-label">Recent ideas</p>
          <div className="tablewrap">
            <table className="data-table">
              <tbody>
                {recent.map((r) => (
                  <tr key={r.id}>
                    <td><Badge text={r.side} tone={r.side === "BUY" ? "green" : "red"} /></td>
                    <td><b>{r.symbol}</b></td>
                    <td className="mono dim">@ {money(r.entry)}</td>
                    <td>{r.planned_rr != null ? `${r.planned_rr}:1` : "—"}</td>
                    <td><Badge text={r.status} tone={statusTone(r.status) as never} /></td>
                    <td className="dim" style={{ fontSize: 12 }}>{r.reject_reason ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
