import { useEffect, useRef, useState } from "react";
import Icon from "./Icon";
import { apiGet, apiPost } from "../../lib/api";
import { useApp } from "../../app-context";

/** One-click real-data loader (shared): kicks the background backfill for
 *  every symbol × sim timeframe, polls progress, and runs `onDone` when the
 *  candles land. The same action the Bot Control Center offers. */
export default function LoadDataButton({ onDone }: { onDone?: () => void }) {
  const app = useApp();
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const pollRef = useRef<number | null>(null);
  // M-2: clear the status poll on unmount so it doesn't keep firing +
  // setState on an unmounted component when the user navigates away mid-load.
  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current); }, []);

  const start = async () => {
    setBusy(true); setProgress("starting…");
    try {
      await apiPost("/data/backfill?candles=6000&timeframes=5m,15m,30m,1h,4h,1d");
      const poll = window.setInterval(async () => {
        try {
          const st = await apiGet<any>("/data/backfill/status");
          setProgress(`${st.done}/${st.total}${st.current ? ` — ${st.current}` : ""}`
            + (st.current_candles ? ` (${st.current_candles})` : ""));
          if (!st.running) {
            window.clearInterval(poll); pollRef.current = null;
            setBusy(false);
            if (st.succeeded > 0) {
              app.toast(`Real data loaded (${st.succeeded} series)`, "success");
              onDone?.();
            } else {
              app.toast("Data load failed — is the exchange reachable from the server?", "error");
            }
          }
        } catch { /* keep polling */ }
      }, 3000);
      pollRef.current = poll;
    } catch {
      setBusy(false);
      app.toast("Could not start the data load — backend reachable?", "error");
    }
  };

  return (
    <button className="btn btn-primary" disabled={busy} onClick={start}>
      <Icon name="play" size={13} /> {busy ? `Loading real data… ${progress}` : "Load real Binance data now"}
    </button>
  );
}
