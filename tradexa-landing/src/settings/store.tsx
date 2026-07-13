import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { settingsSchema, defaultSettings, type Settings, type SettingsSection } from "./schema";

/**
 * Settings persistence. Source of truth is validated against the Zod schema and
 * persisted to localStorage immediately (optimistic). When VITE_API_BASE is
 * configured the same payload is PATCHed to the backend — so the UI is real and
 * functional today and becomes server-backed with no component changes.
 */

const STORAGE_KEY = "tradexa.settings.v1";
const API_BASE = import.meta.env.VITE_API_BASE as string | undefined;
const SECRET = import.meta.env.VITE_WEBHOOK_SECRET as string | undefined;

export type SaveState = "idle" | "saving" | "saved" | "error";

interface Ctx {
  settings: Settings;
  saveState: SaveState;
  backendConnected: boolean;
  /** Patch one section, merging a partial into the existing values. Autosaves. */
  update: <K extends SettingsSection>(section: K, patch: Partial<Settings[K]>) => void;
  /** Replace one section wholesale (used by RHF form submits). Autosaves. */
  setSection: <K extends SettingsSection>(section: K, value: Settings[K]) => void;
  reset: (section?: SettingsSection) => void;
}

const SettingsContext = createContext<Ctx | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used within <SettingsProvider>");
  return ctx;
}

function load(): Settings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultSettings;
    // Merge stored values over defaults so newly-added fields are always present.
    const parsed = settingsSchema.deepPartial().parse(JSON.parse(raw));
    return settingsSchema.parse(mergeDeep(defaultSettings, parsed));
  } catch {
    return defaultSettings;
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(() =>
    typeof window === "undefined" ? defaultSettings : load(),
  );
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const timer = useRef<number | null>(null);

  const persist = useCallback((next: Settings) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* storage full / disabled — the in-memory state still works */
    }
    if (!API_BASE) {
      setSaveState("saved");
      window.setTimeout(() => setSaveState("idle"), 1400);
      return;
    }
    setSaveState("saving");
    fetch(`${API_BASE}/settings/all`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...(SECRET ? { "X-Webhook-Secret": SECRET } : {}) },
      body: JSON.stringify(next),
    })
      .then((r) => setSaveState(r.ok ? "saved" : "error"))
      .catch(() => setSaveState("error"))
      .finally(() => window.setTimeout(() => setSaveState("idle"), 1600));
  }, []);

  const commit = useCallback(
    (next: Settings) => {
      setSettings(next);
      if (timer.current) window.clearTimeout(timer.current);
      // debounce autosave so slider drags don't hammer storage/network
      timer.current = window.setTimeout(() => persist(next), 400);
    },
    [persist],
  );

  const update = useCallback<Ctx["update"]>(
    (section, patch) => {
      setSettings((prev) => {
        const next = { ...prev, [section]: { ...prev[section], ...patch } } as Settings;
        if (timer.current) window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => persist(next), 400);
        return next;
      });
    },
    [persist],
  );

  const setSection = useCallback<Ctx["setSection"]>(
    (section, value) => {
      commit({ ...settings, [section]: value } as Settings);
    },
    [commit, settings],
  );

  const reset = useCallback(
    (section?: SettingsSection) => {
      commit(section ? ({ ...settings, [section]: defaultSettings[section] } as Settings) : defaultSettings);
    },
    [commit, settings],
  );

  const value = useMemo<Ctx>(
    () => ({ settings, saveState, backendConnected: Boolean(API_BASE), update, setSection, reset }),
    [settings, saveState, update, setSection, reset],
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

/** Apply theme + reduced-animation preferences globally as they change. */
// eslint-disable-next-line react-refresh/only-export-components
export function useApplyAppearance() {
  const { settings } = useSettings();
  const { theme, animations, accent } = settings.appearance;
  useEffect(() => {
    const root = document.documentElement;
    const sysDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const dark = theme === "dark" || (theme === "system" && sysDark);
    root.classList.toggle("dark", dark);
    root.classList.toggle("light", !dark);
    root.dataset.animations = animations ? "on" : "off";
    root.style.setProperty("--accent", accent);
  }, [theme, animations, accent]);
}

// tiny deep-merge for plain objects (settings are 2 levels deep)
function mergeDeep<T>(base: T, over: unknown): T {
  if (typeof base !== "object" || base === null || Array.isArray(base)) {
    return (over === undefined ? base : (over as T));
  }
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) };
  const o = (over ?? {}) as Record<string, unknown>;
  for (const k of Object.keys(out)) {
    if (k in o) out[k] = mergeDeep((base as Record<string, unknown>)[k], o[k]);
  }
  return out as T;
}
