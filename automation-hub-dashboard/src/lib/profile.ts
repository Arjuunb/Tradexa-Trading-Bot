// Persistent user profile — stored in the durable per-user settings store
// (namespace "profile"), so it survives logout/login, refresh, and restart
// (the backend mirrors it to Supabase). NOTHING here is fabricated: fields the
// user hasn't set are empty and the UI shows an honest fallback, never fake data.
import { useEffect, useState } from "react";
import { apiGet, apiPostJson } from "./api";

export interface Profile {
  name: string;          // full name (user-set; "" until set)
  email: string;         // email (user-set; "" until set)
  avatar: string;        // data-URL (user-uploaded; "" → initials fallback)
  theme: "dark" | "light" | "system";
  language: string;      // "en" today; others gated
  account_id: string;    // stable, derived from the username (real, not random)
  member_since: string;  // ISO — first time this profile was persisted
  last_login: string;    // ISO — previous session (updated on each load)
}

const EMPTY: Profile = {
  name: "", email: "", avatar: "",
  theme: "dark", language: "en",
  account_id: "", member_since: "", last_login: "",
};

const NS = "profile";
const LS = "hub.profile";           // fast-boot cache only; server is source of truth

// ---- shared store (so the avatar/name update everywhere at once) ----
let _current: Profile = load_cache();
const _subs = new Set<(p: Profile) => void>();
function _emit() { for (const fn of _subs) fn(_current); }

function load_cache(): Profile {
  try {
    const raw = localStorage.getItem(LS);
    if (raw) return { ...EMPTY, ...JSON.parse(raw) };
  } catch { /* private mode */ }
  return { ...EMPTY };
}
function write_cache(p: Profile) {
  try { localStorage.setItem(LS, JSON.stringify(p)); } catch { /* ignore */ }
}

/** A stable, human-readable paper-account id derived from the username — the
 *  same user always gets the same id (real, deterministic; not random). */
export function deriveAccountId(username: string | null | undefined): string {
  const u = (username || "owner").toLowerCase();
  let h = 0;
  for (let i = 0; i < u.length; i++) h = (h * 31 + u.charCodeAt(i)) >>> 0;
  return "PA-" + String(h % 1_000_000).padStart(6, "0");
}

/** Fetch the profile from the durable store and reconcile bookkeeping fields
 *  (account_id / member_since / last_login) without ever inventing user data. */
export async function loadProfile(username: string | null | undefined): Promise<Profile> {
  let data: Partial<Profile> = {};
  try {
    const res = await apiGet<{ ns: string; data: Partial<Profile> }>(`/user/settings?ns=${NS}`);
    data = res?.data ?? {};
  } catch { /* offline → use cache */ data = _current; }

  const nowIso = new Date().toISOString();
  const p: Profile = { ...EMPTY, ..._current, ...data };
  p.account_id = deriveAccountId(username);              // always the real derived id
  if (!p.member_since) p.member_since = nowIso;          // stamp first persistence
  const priorLogin = data.last_login || "";             // show the PREVIOUS login
  const merged: Profile = { ...p, last_login: priorLogin || nowIso };

  _current = merged; write_cache(merged); _emit();

  // record this login as "last_login" for next time (best-effort, non-blocking)
  const toPersist: Profile = { ...merged, last_login: nowIso };
  void saveProfile(toPersist, { silent: true });
  return merged;
}

/** Persist a full profile (or patch) to the durable store. */
export async function saveProfile(patch: Partial<Profile>, opts?: { silent?: boolean }): Promise<Profile> {
  const next: Profile = { ..._current, ...patch };
  _current = next; write_cache(next);
  if (!opts?.silent) _emit();
  try { await apiPostJson("/user/settings", { ns: NS, data: next }); } catch { /* stays cached */ }
  return next;
}

export function getProfile(): Profile { return _current; }

/** Subscribe a React component to profile changes. */
export function useProfile(): Profile {
  const [p, setP] = useState<Profile>(_current);
  useEffect(() => {
    const fn = (np: Profile) => setP(np);
    _subs.add(fn);
    setP(_current);
    return () => { _subs.delete(fn); };
  }, []);
  return p;
}

// ---------------------------------------------------------------- helpers
export function initials(name: string, username: string | null | undefined): string {
  const src = (name || "").trim() || (username || "").trim();
  if (!src) return "PA";
  const parts = src.split(/[\s._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return src.slice(0, 2).toUpperCase();
}

const _UA_BROWSERS: [RegExp, string][] = [
  [/edg\//i, "Edge"], [/opr\//i, "Opera"], [/chrome\//i, "Chrome"],
  [/firefox\//i, "Firefox"], [/safari\//i, "Safari"],
];
const _UA_OS: [RegExp, string][] = [
  [/windows/i, "Windows"], [/mac os x|macintosh/i, "macOS"], [/android/i, "Android"],
  [/iphone|ipad|ios/i, "iOS"], [/linux/i, "Linux"],
];
export interface SessionInfo { browser: string; os: string; device: string; timezone: string; }
export function sessionInfo(): SessionInfo {
  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
  const browser = _UA_BROWSERS.find(([re]) => re.test(ua))?.[1] ?? "Unknown browser";
  const os = _UA_OS.find(([re]) => re.test(ua))?.[1] ?? "Unknown OS";
  const device = /mobile|iphone|android/i.test(ua) ? "Mobile" : /ipad|tablet/i.test(ua) ? "Tablet" : "Desktop";
  let timezone = "—";
  try { timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "—"; } catch { /* ignore */ }
  return { browser, os, device, timezone };
}

export const AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const AVATAR_MAX_BYTES = 5 * 1024 * 1024;

/** Validate + center-crop-to-square + downscale an uploaded image to a compact
 *  data-URL (≤256px). Rejects wrong types / oversize. Returns the data-URL. */
export function fileToAvatar(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!AVATAR_TYPES.includes(file.type)) return reject(new Error("Use PNG, JPG, JPEG or WEBP."));
    if (file.size > AVATAR_MAX_BYTES) return reject(new Error("Image must be 5MB or smaller."));
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const side = Math.min(img.width, img.height);
      const sx = (img.width - side) / 2, sy = (img.height - side) / 2;
      const out = 256;
      const canvas = document.createElement("canvas");
      canvas.width = out; canvas.height = out;
      const ctx = canvas.getContext("2d");
      if (!ctx) return reject(new Error("Canvas unavailable."));
      ctx.drawImage(img, sx, sy, side, side, 0, 0, out, out);
      try { resolve(canvas.toDataURL("image/webp", 0.9)); }
      catch { reject(new Error("Could not process image.")); }
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Invalid image file.")); };
    img.src = url;
  });
}
