import Icon from "./Icon";
import { API_BASE } from "../../lib/api";

/** Shared "backend not reachable" banner (M-1). Render when a page's primary
 *  data query errors with no data, so an outage is never shown as a real,
 *  empty ($0) account — critical on a trading product. */
export default function OfflineBanner({ show, what = "live data" }: { show: boolean; what?: string }) {
  if (!show) return null;
  return (
    <div className="card" style={{ borderColor: "#ef4444", display: "flex", alignItems: "center", gap: 10 }}>
      <Icon name="warning" size={16} className="neg" />
      <span>
        <b>Backend not reachable.</b> The numbers below are not live — start the API at{" "}
        <span className="mono">{API_BASE}</span> to see {what}. This is a connection issue, not an empty account.
      </span>
    </div>
  );
}
