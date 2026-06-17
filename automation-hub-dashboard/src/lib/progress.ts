// Records the safety-flow progression locally (Backtest -> Simulation -> Paper
// -> Live). Paper evidence comes from the backend (real closed trades); the
// backtest/simulation steps are marked here when the user actually runs them.
export type Stage = "backtest" | "simulation";

const KEY = "hub_safety_progress";

type Flags = Record<Stage, boolean>;

export function getProgress(): Flags {
  try {
    return { backtest: false, simulation: false, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return { backtest: false, simulation: false };
  }
}

export function markDone(stage: Stage): void {
  const cur = getProgress();
  cur[stage] = true;
  try { localStorage.setItem(KEY, JSON.stringify(cur)); } catch { /* ignore */ }
}
