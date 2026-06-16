// Live API client for the Automation Hub backend (FastAPI).
//
// Base URL is configurable via VITE_API_BASE (defaults to the local backend).
// Control/engine actions are secret-gated; the dev secret is configurable via
// VITE_WEBHOOK_SECRET. When the backend isn't running, hooks expose `error`
// so pages can show a "start the backend" hint instead of fake data.
import { useCallback, useEffect, useRef, useState } from "react";

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";
const SECRET = (import.meta.env.VITE_WEBHOOK_SECRET as string | undefined) ?? "dev-webhook-secret";

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "X-Webhook-Secret": SECRET },
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export interface LiveState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refetch: () => void;
}

/** Poll a GET endpoint every `intervalMs` and expose data/error/loading. */
export function useLive<T>(path: string, intervalMs = 2500): LiveState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const d = await apiGet<T>(path);
      if (!alive.current) return;
      setData(d);
      setError(null);
    } catch (e) {
      if (!alive.current) return;
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    load();
    const id = setInterval(load, intervalMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [load, intervalMs]);

  return { data, error, loading, refetch: load };
}

// ---- response shapes (match the FastAPI endpoints) ----
export interface PaperAccount {
  starting_balance: number;
  balance: number;
  realized_pnl: number;
  open_positions: number;
}
export interface LedgerPosition {
  id: string; symbol: string; side: string; size: number;
  entry: number; stop: number | null; status: string; pnl: number;
  opened_at: string; closed_at: string | null;
}
export interface PaperTradeRow {
  id: string; alert_id: string | null; symbol: string; side: string; size: number;
  entry: number; stop: number | null; exit: number | null; pnl: number | null;
  rr: number | null; status: string; opened_at: string; closed_at: string | null;
}
export interface LogRow {
  id: string; ts: string; symbol: string; level: string; stage: string; message: string;
}
export interface AlertRow {
  id: string; ts: string; severity: string; category: string; title: string; detail: string; read: number;
}
export interface EngineStatus {
  running: boolean; symbols: string[]; timeframe: string; interval: number;
  started_at: string | null; bars: number; signals: number; trades: number; rejections: number;
}
export interface ControlState { state: "Active" | "Paused" | "Stopped"; }

/** Short "HH:MM:SS" from an ISO timestamp. */
export function hhmmss(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = iso.includes("T") ? iso.split("T")[1] : iso;
  return t.slice(0, 8);
}
