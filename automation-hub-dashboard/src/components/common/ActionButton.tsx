import { useState, type ReactNode } from "react";
import Icon from "./Icon";
import { useApp } from "../../app-context";

/** Reusable action-button safety pattern.
 *
 *  Wrap any async action and get, for free:
 *   - a loading state (spinner + optional busy label) while it runs
 *   - double-click / concurrent-run protection (ignores clicks while busy)
 *   - a success toast on resolve and an error toast on reject
 *   - the button stays disabled until the request settles
 *
 *  Visual output is a plain `.btn` — no redesign; drop-in for existing buttons.
 */
export default function ActionButton({
  onAction, children, busyLabel, successMsg, errorMsg,
  className = "btn btn-soft", disabled = false, title, icon, confirm,
}: {
  onAction: () => Promise<unknown>;
  children: ReactNode;
  busyLabel?: string;
  successMsg?: string;
  errorMsg?: string;
  className?: string;
  disabled?: boolean;
  title?: string;
  icon?: string;
  confirm?: string;                // optional window.confirm gate for destructive actions
}) {
  const app = useApp();
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (busy || disabled) return;                       // double-click guard
    if (confirm && !window.confirm(confirm)) return;
    setBusy(true);
    try {
      await onAction();
      if (successMsg) app.toast(successMsg, "success");
    } catch (e) {
      app.toast(errorMsg ?? (e instanceof Error ? e.message : "Action failed"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <button type="button" className={className} disabled={disabled || busy}
      title={title} aria-busy={busy} onClick={run}>
      {busy
        ? <><Icon name="refresh" size={13} className="spin" /> {busyLabel ?? "Working…"}</>
        : <>{icon && <Icon name={icon} size={13} />} {children}</>}
    </button>
  );
}
