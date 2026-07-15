import { useEffect, useState } from "react";
import { API_BASE } from "./api";

/** Persistent per-user dashboard preferences (filters, chart timeframes,
 *  collapsed sections, sorting). The backend `user_settings` table is the
 *  source of truth (session-authenticated, isolated per user); localStorage is
 *  only the fast-boot cache. Every change saves immediately (debounced 600ms).
 *  Signed-out / offline: falls back to localStorage silently. */

const NS = "dashboard";
const LS = (key: string) => `hubpref.${key}`;

let blob: Record<string, unknown> | null = null;   // server truth once loaded
let loadPromise: Promise<void> | null = null;
let saveTimer: number | null = null;
const listeners = new Map<string, Set<(v: unknown) => void>>();

function loadOnce(): Promise<void> {
  if (!loadPromise) {
    loadPromise = fetch(`${API_BASE}/user/settings?ns=${NS}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { data?: Record<string, unknown> } | null) => {
        blob = body?.data ?? {};
        for (const [key, subs] of listeners) {
          if (blob && key in blob) {
            try { localStorage.setItem(LS(key), JSON.stringify(blob[key])); } catch { /* cache */ }
            subs.forEach((fn) => fn(blob![key]));
          }
        }
      })
      .catch(() => { blob = null; });   // offline / signed-out -> local cache only
  }
  return loadPromise;
}

function scheduleSave() {
  if (blob === null) return;           // never save before (or without) a load
  if (saveTimer) window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    fetch(`${API_BASE}/user/settings`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ns: NS, data: blob }),
    }).catch(() => { /* offline — localStorage still has it */ });
  }, 600);
}

/** Drop-in replacement for useState that survives refresh, logout and login. */
export function usePref<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(LS(key));
      if (raw !== null) return JSON.parse(raw) as T;
    } catch { /* fall through to default */ }
    return initial;
  });

  useEffect(() => {
    let sub = listeners.get(key);
    if (!sub) listeners.set(key, (sub = new Set()));
    const fn = (v: unknown) => setValue(v as T);
    sub.add(fn);
    void loadOnce().then(() => {
      if (blob && key in blob) setValue(blob[key] as T);
    });
    return () => { sub!.delete(fn); };
  }, [key]);

  const set = (v: T) => {
    setValue(v);
    try { localStorage.setItem(LS(key), JSON.stringify(v)); } catch { /* cache */ }
    if (blob !== null) {
      blob[key] = v;
      scheduleSave();
    }
  };
  return [value, set];
}

/** Explicit reset only — wired to the user's "Reset dashboard" action. */
export async function resetDashboardPrefs(): Promise<void> {
  for (let i = localStorage.length - 1; i >= 0; i--) {
    const k = localStorage.key(i);
    if (k && k.startsWith("hubpref.")) localStorage.removeItem(k);
  }
  blob = {};
  await fetch(`${API_BASE}/user/settings?ns=${NS}`, {
    method: "DELETE",
    credentials: "include",
  }).catch(() => { /* offline */ });
}
