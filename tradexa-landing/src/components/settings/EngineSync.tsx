import { LogIn, PlugZap, TriangleAlert } from "lucide-react";

/**
 * Honest sync-status banner for settings pages that can drive the live engine.
 * Three states: synced (operator signed in, engine reachable), engine error,
 * or signed out (changes are local-only and do NOT affect the bot).
 */
export function EngineSyncBanner({
  signedIn,
  error,
}: {
  signedIn: boolean;
  error?: string | null;
}) {
  if (signedIn && !error) {
    return (
      <div className="mb-5 flex items-center gap-2.5 rounded-xl border border-emerald/25 bg-emerald/[0.06] px-4 py-2.5 text-sm text-emerald-soft">
        <PlugZap className="h-4 w-4 shrink-0" />
        Synced with the live engine — changes below apply to the bot immediately and persist.
      </div>
    );
  }
  if (signedIn && error) {
    return (
      <div className="mb-5 flex items-center gap-2.5 rounded-xl border border-loss/25 bg-loss/[0.06] px-4 py-2.5 text-sm text-loss-soft">
        <TriangleAlert className="h-4 w-4 shrink-0" />
        Engine unreachable ({error}) — values shown may be stale; changes are saved locally only.
      </div>
    );
  }
  return (
    <div className="mb-5 flex flex-wrap items-center gap-2.5 rounded-xl border border-gold/25 bg-gold/[0.06] px-4 py-2.5 text-sm text-gold-soft">
      <LogIn className="h-4 w-4 shrink-0" />
      <span>
        Not signed in — changes here are saved locally and do <b>not</b> change the bot.{" "}
        <a href="/login" className="font-semibold underline underline-offset-2 hover:text-gold">
          Sign in
        </a>{" "}
        to control the live engine.
      </span>
    </div>
  );
}

/** Small inline marker for rows that have no engine equivalent (yet). */
export function LocalTag() {
  return (
    <span className="ml-1.5 rounded border border-line px-1 py-0.5 align-middle font-mono text-[10px] uppercase tracking-wider text-white/35">
      local
    </span>
  );
}
