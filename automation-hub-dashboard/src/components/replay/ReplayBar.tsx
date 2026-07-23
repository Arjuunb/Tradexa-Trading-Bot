import { useEffect, useState } from "react";
import { SkipBack, ChevronLeft, Play, Pause, ChevronRight, X } from "lucide-react";

/** In-terminal replay controls — scrub the chart cursor back through the loaded
 *  candles and step/play forward. Every replayed bar is REAL: the chart shows
 *  [0..idx] with the strategy's own causal markers/decisions at that bar, so you
 *  watch exactly when the bot detected a setup and acted. No fabricated frames. */
export default function ReplayBar({
  len, idx, setIdx, onExit, timeLabel,
}: {
  len: number;
  idx: number;
  setIdx: (n: number) => void;
  onExit: () => void;
  timeLabel?: string;
}) {
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const last = Math.max(0, len - 1);
  const atEnd = idx >= last;

  // advance one bar per tick while playing; auto-pause at the last candle
  useEffect(() => {
    if (!playing) return;
    if (idx >= last) { setPlaying(false); return; }
    const ms = Math.max(120, Math.round(800 / speed));
    const t = window.setTimeout(() => setIdx(Math.min(last, idx + 1)), ms);
    return () => window.clearTimeout(t);
  }, [playing, idx, speed, last, setIdx]);

  const restart = () => { setPlaying(false); setIdx(Math.max(0, len - 160)); };
  const step = (d: number) => { setPlaying(false); setIdx(Math.min(last, Math.max(0, idx + d))); };

  return (
    <div className="rp-bar" role="group" aria-label="Replay controls">
      <span className="rp-tag">REPLAY</span>
      <button className="chip-btn" title="Restart (~160 bars back)" onClick={restart}><SkipBack size={13} /></button>
      <button className="chip-btn" title="Step back" onClick={() => step(-1)} disabled={idx <= 0}><ChevronLeft size={14} /></button>
      <button className={`chip-btn ${playing ? "active" : ""}`} title={playing ? "Pause" : "Play"}
              onClick={() => (atEnd ? (setIdx(Math.max(0, len - 160)), setPlaying(true)) : setPlaying((p) => !p))}>
        {playing ? <Pause size={14} /> : <Play size={14} />}
      </button>
      <button className="chip-btn" title="Step forward" onClick={() => step(1)} disabled={atEnd}><ChevronRight size={14} /></button>

      <input className="rp-scrub" type="range" min={0} max={last} value={Math.min(idx, last)} aria-label="Replay position"
             onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} />

      <div className="rp-speeds">
        {[0.5, 1, 2, 4].map((s) => (
          <button key={s} className={`rp-speed ${speed === s ? "active" : ""}`} onClick={() => setSpeed(s)}>{s}×</button>
        ))}
      </div>

      <span className="rp-pos mono">{Math.min(idx, last) + 1}/{len}{timeLabel ? ` · ${timeLabel.replace("T", " ").slice(5, 16)}` : ""}</span>
      <button className="chip-btn rp-exit" title="Exit replay — back to live" onClick={() => { setPlaying(false); onExit(); }}>
        <X size={13} /> Live
      </button>
    </div>
  );
}
