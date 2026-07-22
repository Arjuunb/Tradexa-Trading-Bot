import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  User, IdCard, Clock, Monitor, Globe, Palette, Shield, KeyRound,
  Link2, SlidersHorizontal, Bell, Download, DatabaseBackup, LogOut, Pencil,
  Upload, Trash2, Check, ChevronRight, X, type LucideIcon,
} from "lucide-react";
import Modal from "../common/Modal";
import { useApp } from "../../app-context";
import {
  apiGet, apiPost, apiDownload, APP_ORIGIN, useLive,
  type PaperAccount, type RiskSummary, type SystemStatus, type StrategyPerformance,
} from "../../lib/api";
import { signedMoney } from "../../lib/format";
import {
  useProfile, loadProfile, saveProfile, fileToAvatar, initials, sessionInfo,
  type Profile,
} from "../../lib/profile";

const money = (n: number | undefined | null) =>
  n == null ? "—" : `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

function fmtDate(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { month: "short", year: "numeric", day: "numeric" });
}
function fmtDateTime(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const today = new Date();
  const same = d.toDateString() === today.toDateString();
  const t = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return same ? `Today ${t}` : `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${t}`;
}

// ---- avatar (image or initials) ----
function Avatar({ profile, username, size = 40 }: { profile: Profile; username: string | null; size?: number }) {
  if (profile.avatar) {
    return <img className="pm-avatar-img" src={profile.avatar} alt="" width={size} height={size}
                style={{ width: size, height: size }} />;
  }
  return <div className="pm-avatar-fallback" style={{ width: size, height: size, fontSize: size * 0.36 }}>
    {initials(profile.name, username)}
  </div>;
}

export default function ProfileMenu() {
  const app = useApp();
  const profile = useProfile();
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [edit, setEdit] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [busy, setBusy] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // real account data
  const acct = useLive<PaperAccount>("/paper/account", 8000);
  const risk = useLive<RiskSummary>("/risk/summary", 8000);
  const sys = useLive<SystemStatus>("/system/status", 8000);
  const perf = useLive<StrategyPerformance>("/strategy/performance", 12000);
  const session = useMemo(() => sessionInfo(), []);

  // who am I + load persisted profile
  useEffect(() => {
    let alive = true;
    void apiGet<{ authenticated: boolean; user: string | null }>("/auth/status")
      .then((s) => { if (alive) { setUsername(s.user); void loadProfile(s.user); } })
      .catch(() => { if (alive) void loadProfile(null); });
    return () => { alive = false; };
  }, []);

  // close on outside click / Esc; focus management
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); triggerRef.current?.focus(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  // edit draft
  const [draftName, setDraftName] = useState("");
  const [draftEmail, setDraftEmail] = useState("");
  useEffect(() => { if (edit) { setDraftName(profile.name); setDraftEmail(profile.email); } }, [edit, profile.name, profile.email]);

  const pickAvatar = useCallback(async (file: File | undefined) => {
    if (!file) return;
    try { const data = await fileToAvatar(file); await saveProfile({ avatar: data }); app.toast("Avatar updated.", "success"); }
    catch (e) { app.toast((e as Error).message || "Could not set avatar.", "error"); }
  }, [app]);

  const saveEdit = async () => {
    setBusy(true);
    await saveProfile({ name: draftName.trim(), email: draftEmail.trim() });
    setBusy(false); setEdit(false);
    app.toast("Profile saved.", "success");
  };

  const setTheme = async (theme: Profile["theme"]) => {
    if (theme === "light") { app.toast("Full light theme is coming soon — the app is dark-first today.", "info"); return; }
    await saveProfile({ theme });
    try { document.documentElement.setAttribute("data-theme", theme); } catch { /* ignore */ }
    app.toast(`Theme: ${theme}`, "success");
  };

  const nav = (page: string) => { setOpen(false); app.go(page); };

  const doExport = async (path: string, filename: string, label: string) => {
    try { await apiDownload(path, filename); app.toast(`${label} downloaded.`, "success"); }
    catch { app.toast(`${label} unavailable (backend offline).`, "error"); }
  };
  const backupSettings = () => {
    try {
      const blob = new Blob([JSON.stringify(profile, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "tradelogx-profile-backup.json";
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      app.toast("Settings backup downloaded.", "success");
    } catch { app.toast("Backup failed.", "error"); }
  };

  const logout = async () => {
    setBusy(true);
    try { await saveProfile(profile); } catch { /* persist unsaved prefs */ }
    try { await apiPost("/auth/logout"); } catch { /* clear anyway */ }
    try { localStorage.removeItem("hub.profile"); } catch { /* ignore */ }
    window.location.href = `${APP_ORIGIN}/login`;
  };

  // ---- real stats (or honest fallback) ----
  const balance = acct.data ? (acct.data.current_equity ?? acct.data.available_balance) : undefined;
  const openPos = risk.data?.open_positions ?? acct.data?.open_positions;
  const closed = perf.data?.trades;
  const winRate = perf.data?.win_rate;
  const totalPnl = perf.data?.realized_pnl ?? risk.data?.realized_pnl;
  const strat = sys.data?.strategy;
  const riskPct = risk.data?.risk_per_trade_pct != null ? risk.data.risk_per_trade_pct * 100 : undefined;

  return (
    <div className="pm-root" ref={rootRef}>
      <button ref={triggerRef} type="button" className={`profile pm-trigger ${open ? "open" : ""}`}
              aria-haspopup="menu" aria-expanded={open} aria-label="Account menu"
              onClick={() => setOpen((v) => !v)}>
        <Avatar profile={profile} username={username} size={34} />
        <div className="profile-meta">
          <b>{profile.name || "Paper Account"}</b>
          <span className="dim">Simulation</span>
        </div>
      </button>

      {open && (
        <div className="pm-panel" role="menu" aria-label="Account">
          {/* 1 — Account information */}
          <div className="pm-head">
            <button className="pm-avatar-btn" onClick={() => fileRef.current?.click()} title="Change avatar" aria-label="Change avatar">
              <Avatar profile={profile} username={username} size={56} />
              <span className="pm-avatar-edit"><Pencil size={12} /></span>
            </button>
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden
                   onChange={(e) => { void pickAvatar(e.target.files?.[0]); e.target.value = ""; }} />
            <div className="pm-id">
              <div className="pm-name">{profile.name || "Add your name"}</div>
              <div className="pm-sub">{username ? `@${username}` : "—"}</div>
              <div className="pm-sub pm-email">{profile.email || "Add your email"}</div>
            </div>
            <button className="pm-edit-btn" onClick={() => setEdit((v) => !v)} aria-label="Edit profile">
              {edit ? <X size={16} /> : <Pencil size={16} />}
            </button>
          </div>

          <span className="pm-badge">Paper Trading Account</span>

          {edit && (
            <div className="pm-edit" onDragOver={(e) => e.preventDefault()}
                 onDrop={(e) => { e.preventDefault(); void pickAvatar(e.dataTransfer.files?.[0]); }}>
              <label>Full name<input value={draftName} maxLength={60} placeholder="e.g. Arjun Bhatta"
                     onChange={(e) => setDraftName(e.target.value)} /></label>
              <label>Email<input type="email" value={draftEmail} maxLength={120} placeholder="you@email.com"
                     onChange={(e) => setDraftEmail(e.target.value)} /></label>
              <div className="pm-avatar-row">
                <button className="btn btn-soft btn-sm" onClick={() => fileRef.current?.click()}><Upload size={13} /> Upload</button>
                {profile.avatar && <button className="btn btn-ghost btn-sm" onClick={() => void saveProfile({ avatar: "" })}><Trash2 size={13} /> Remove</button>}
                <span className="dim pm-tiny">PNG/JPG/WEBP · ≤5MB · drag &amp; drop</span>
              </div>
              <div className="pm-actions-row">
                <button className="btn btn-sm" disabled={busy} onClick={() => void saveEdit()}><Check size={13} /> Save</button>
                <button className="btn btn-ghost btn-sm" onClick={() => setEdit(false)}>Cancel</button>
              </div>
            </div>
          )}

          <div className="pm-kv">
            <span><IdCard size={13} /> Account ID</span><b className="mono">{profile.account_id || "—"}</b>
            <span><User size={13} /> Type</span><b>Paper · <span className="dim">Live (soon)</span></b>
            <span><Clock size={13} /> Member since</span><b>{fmtDate(profile.member_since)}</b>
            <span><Clock size={13} /> Last login</span><b>{fmtDateTime(profile.last_login)}</b>
          </div>

          {/* 5 — Account statistics (real) */}
          <p className="pm-sect">Account</p>
          <div className="pm-stats">
            <div className="pm-stat"><span>Balance</span><b>{money(balance)}</b></div>
            <div className="pm-stat"><span>Open positions</span><b>{openPos ?? "—"}</b></div>
            <div className="pm-stat"><span>Closed trades</span><b>{closed ?? "—"}</b></div>
            <div className="pm-stat"><span>Win rate</span><b>{winRate != null ? `${winRate.toFixed(1)}%` : "—"}</b></div>
            <div className="pm-stat"><span>Total P&amp;L</span>
              <b className={(totalPnl ?? 0) >= 0 ? "pos" : "neg"}>{totalPnl != null ? signedMoney(totalPnl) : "—"}</b></div>
            <div className="pm-stat"><span>Strategy</span><b className="pm-clip">{strat || "—"}</b></div>
            <div className="pm-stat"><span>Risk / trade</span><b>{riskPct != null ? `${riskPct.toFixed(2)}%` : "—"}</b></div>
          </div>

          {/* 3 — Settings shortcuts */}
          <p className="pm-sect">Settings</p>
          <div className="pm-grid">
            <Shortcut icon={User} label="Profile" onClick={() => { setEdit(true); }} />
            <Shortcut icon={SlidersHorizontal} label="Trading Prefs" onClick={() => nav("Settings")} />
            <Shortcut icon={SquareTerminalIcon} label="Paper Settings" onClick={() => nav("Paper Trading")} />
            <Shortcut icon={Bell} label="Notifications" onClick={() => nav("Settings")} />
            <Shortcut icon={Palette} label="Appearance" onClick={() => nav("Settings")} />
            <Shortcut icon={Shield} label="Security" onClick={() => nav("Settings")} />
            <Shortcut icon={KeyRound} label="API Keys" soon />
            <Shortcut icon={Link2} label="Exchanges" soon />
          </div>

          {/* 6 — Theme */}
          <p className="pm-sect">Theme</p>
          <div className="pm-seg">
            {(["dark", "system", "light"] as const).map((t) => (
              <button key={t} className={`pm-seg-btn ${profile.theme === t ? "active" : ""}`}
                      disabled={t === "light"} title={t === "light" ? "Coming soon" : ""}
                      onClick={() => void setTheme(t)}>
                {t}{t === "light" && <span className="pm-soon">soon</span>}
              </button>
            ))}
          </div>

          {/* 7 — Language */}
          <p className="pm-sect">Language</p>
          <div className="pm-seg">
            <button className="pm-seg-btn active"><Globe size={12} /> English</button>
            <button className="pm-seg-btn" disabled title="Coming soon">नेपाली <span className="pm-soon">soon</span></button>
            <button className="pm-seg-btn" disabled title="Coming soon">More <span className="pm-soon">soon</span></button>
          </div>

          {/* 4 — Session */}
          <p className="pm-sect">Current session</p>
          <div className="pm-kv pm-session">
            <span><Monitor size={13} /> Device</span><b>{session.device} · {session.os}</b>
            <span>Browser</span><b>{session.browser}</b>
            <span>Timezone</span><b>{session.timezone}</b>
            <span>Signed in</span><b>{fmtDateTime(profile.last_login)}</b>
          </div>

          {/* 8 — Account actions */}
          <p className="pm-sect">Account</p>
          <div className="pm-list">
            <Action icon={Pencil} label="Edit profile" onClick={() => setEdit(true)} />
            <Action icon={KeyRound} label="Change password" onClick={() => nav("Settings")} />
            <Action icon={Monitor} label="Manage sessions" note="this device" onClick={() => nav("Settings")} />
            <Action icon={Download} label="Export account data (JSON)"
                    onClick={() => void doExport("/audit/export?fmt=json", "tradelogx-account.json", "Account data")} />
            <Action icon={Download} label="Download trade history (CSV)"
                    onClick={() => void doExport("/paper/trades/export?fmt=csv", "tradelogx-trades.csv", "Trade history")} />
            <Action icon={DatabaseBackup} label="Backup settings" onClick={backupSettings} />
          </div>

          {/* 9 — Logout */}
          <button className="pm-logout" onClick={() => setConfirmLogout(true)}>
            <LogOut size={15} /> Log out
          </button>
        </div>
      )}

      <Modal open={confirmLogout} title="Log out" onClose={() => setConfirmLogout(false)}>
        <p className="dim" style={{ marginBottom: 14 }}>
          You'll be signed out and returned to the login screen. Your saved profile and settings are kept.
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setConfirmLogout(false)}>Cancel</button>
          <button className="btn btn-sm pm-logout-confirm" disabled={busy} onClick={() => void logout()}>
            <LogOut size={13} /> Log out
          </button>
        </div>
      </Modal>
    </div>
  );
}

// small square-terminal glyph reuse (paper trading)
function SquareTerminalIcon(props: { size?: number }) {
  const s = props.size ?? 16;
  return <Monitor size={s} />;
}

function Shortcut({ icon: I, label, onClick, soon }: { icon: LucideIcon; label: string; onClick?: () => void; soon?: boolean }) {
  return (
    <button className="pm-short" disabled={soon} onClick={onClick} title={soon ? "Coming soon" : label}>
      <I size={16} /><span>{label}</span>{soon && <span className="pm-soon">soon</span>}
    </button>
  );
}
function Action({ icon: I, label, note, onClick }: { icon: LucideIcon; label: string; note?: string; onClick?: () => void }) {
  return (
    <button className="pm-item" role="menuitem" onClick={onClick}>
      <I size={15} /><span>{label}</span>
      {note && <span className="dim pm-tiny">{note}</span>}
      <ChevronRight size={14} className="pm-item-caret" />
    </button>
  );
}
