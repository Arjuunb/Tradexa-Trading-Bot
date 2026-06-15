import { useMemo, useState } from "react";
import type { AlertSeverity } from "../types";
import Icon from "../components/common/Icon";
import Modal from "../components/common/Modal";
import { Badge, Field, PageHeader } from "../components/common/ui";
import { platformAlerts as seed } from "../data/mock";

const sevTone = (s: AlertSeverity) => ({ Info: "blue", Warning: "amber", Critical: "red" }[s] as any);
const catTone = (c: string) => ({ Risk: "purple", Trade: "green", System: "blue", Connection: "amber" }[c] as any);

export default function AlertsPage() {
  const [items, setItems] = useState(seed);
  const [tab, setTab] = useState<"Active" | "Past">("Active");
  const [showRule, setShowRule] = useState(false);

  const visible = useMemo(() => items.filter((a) => (tab === "Active" ? a.active : !a.active)), [items, tab]);
  const unread = items.filter((a) => a.active && !a.read).length;

  const markRead = (id: string) => setItems((p) => p.map((a) => (a.id === id ? { ...a, read: true } : a)));
  const remove = (id: string) => setItems((p) => p.filter((a) => a.id !== id));

  return (
    <>
      <PageHeader
        title="Alerts"
        subtitle={`${unread} unread active alerts`}
        actions={<button className="btn btn-primary" onClick={() => setShowRule(true)}><Icon name="plus" size={15} /> Create Alert Rule</button>}
      />

      <div className="tabs standalone">
        {(["Active", "Past"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t} <span className="tab-count">({items.filter((a) => (t === "Active" ? a.active : !a.active)).length})</span>
          </button>
        ))}
      </div>

      <div className="alert-stack">
        {visible.map((a) => (
          <div className={`card alert-card ${!a.read && a.active ? "unread" : ""}`} key={a.id}>
            <span className={`alert-icon ${sevTone(a.severity) === "red" ? "neg" : sevTone(a.severity) === "amber" ? "amber" : "blue"}`}>
              <Icon name={a.severity === "Critical" ? "warning" : a.severity === "Warning" ? "warning" : "info"} size={16} />
            </span>
            <div className="alert-body">
              <div className="alert-titlerow">
                <b>{a.title}</b>
                <Badge text={a.severity} tone={sevTone(a.severity)} />
                <Badge text={a.category} tone={catTone(a.category)} />
              </div>
              <span className="dim">{a.detail}</span>
            </div>
            <span className="alert-time">{a.time}</span>
            <div className="row-actions">
              {!a.read && <button className="icon-btn sm" title="Mark as read" onClick={() => markRead(a.id)}><Icon name="check" size={14} /></button>}
              <button className="icon-btn sm neg" title="Delete" onClick={() => remove(a.id)}><Icon name="close" size={14} /></button>
            </div>
          </div>
        ))}
        {visible.length === 0 && <div className="empty-state">No {tab.toLowerCase()} alerts.</div>}
      </div>

      <Modal open={showRule} title="Create Alert Rule" onClose={() => setShowRule(false)}>
        <div className="modal-form">
          <Field label="Alert type"><select><option>Risk</option><option>Trade</option><option>System</option><option>Connection</option></select></Field>
          <Field label="Severity"><select><option>Info</option><option>Warning</option><option>Critical</option></select></Field>
          <Field label="Condition"><input placeholder="e.g. daily loss > 50% of limit" /></Field>
        </div>
        <p className="dim">Notification delivery (email / Telegram / Discord) is a placeholder for a later phase.</p>
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={() => setShowRule(false)}>Cancel</button>
          <button className="btn btn-primary" onClick={() => setShowRule(false)}>Create</button>
        </div>
      </Modal>
    </>
  );
}
