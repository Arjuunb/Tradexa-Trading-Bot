import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, LogIn, RefreshCw, ShieldAlert } from "lucide-react";
import { SettingsHeader, Section, NotConnected } from "@/components/settings/primitives";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { hubConfig, hubFetch } from "@/lib/hub";
import { useToast } from "@/lib/toast";

/**
 * LIVE strategy manager. The engine runs exactly ONE strategy across all
 * symbols; activating another swaps the running engine (paper mode) via the
 * real backend — the same /strategy/select the dashboard uses. Requires a
 * signed-in operator (the backend only injects the control config into this
 * page for authenticated sessions); anonymous visitors get an honest
 * sign-in prompt, never a mock.
 */

interface CatalogEntry {
  key: string;
  label: string;
  desc: string;
}

interface StrategyList {
  active: string;
  timeframe: string;
  strategies: CatalogEntry[];
}

export default function Strategies() {
  const { toast } = useToast();
  const signedIn = hubConfig() !== null;
  const [list, setList] = useState<StrategyList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<CatalogEntry | null>(null);

  const load = useCallback(() => {
    if (!signedIn) return;
    hubFetch<StrategyList>("/strategy/list")
      .then((d) => {
        setList(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [signedIn]);

  useEffect(() => {
    load();
  }, [load]);

  const activate = async (s: CatalogEntry) => {
    setBusy(s.key);
    try {
      await hubFetch("/strategy/select", {
        method: "POST",
        body: JSON.stringify({ strategy: s.key }),
      });
      toast(`Engine now trading ${s.label} (paper) — the choice is persisted.`, "success");
      load();
    } catch {
      toast("Could not switch strategy — is the backend reachable?", "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <SettingsHeader
        title="Strategies"
        description="The engine trades ONE active strategy across all symbols. Activating another swaps the running engine live (paper mode)."
      />

      <div className="space-y-5">
        {!signedIn ? (
          <Section title="Live strategy">
            <div className="py-3">
              <NotConnected
                icon={LogIn}
                title="Sign in to manage the live strategy"
                detail="Switching the engine's strategy is an operator action. Sign in to your dashboard session and reload this page — the switcher activates automatically."
              />
              <div className="mt-4 flex justify-center">
                <a href="/login">
                  <Button variant="secondary">
                    <LogIn className="h-4 w-4" /> Sign in
                  </Button>
                </a>
              </div>
            </div>
          </Section>
        ) : (
          <Section
            title="Live strategy"
            description={
              list
                ? `Engine timeframe ${list.timeframe} · one active strategy at a time.`
                : "Loading the live catalog from the engine…"
            }
            action={
              <Button size="sm" variant="ghost" onClick={load}>
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </Button>
            }
          >
            {error && (
              <div className="my-3 flex items-start gap-2 rounded-lg border border-loss/30 bg-loss/[0.06] px-3 py-2 text-sm text-loss-soft">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                Could not reach the engine ({error}). Refresh to retry.
              </div>
            )}
            <div className="divide-y divide-line/60">
              {(list?.strategies ?? []).map((s) => {
                const isActive = s.key === list?.active;
                return (
                  <div key={s.key} className="flex flex-wrap items-center gap-3 py-3.5">
                    <div className="min-w-0 flex-1">
                      <p className="flex items-center gap-2 text-sm font-medium text-white">
                        {s.label}
                        {isActive && <Badge tone="emerald">Active · {list?.timeframe}</Badge>}
                      </p>
                      <p className="mt-0.5 text-[13px] text-white/45">{s.desc}</p>
                    </div>
                    {isActive ? (
                      <span className="inline-flex items-center gap-1.5 text-[13px] text-white/50">
                        <CheckCircle2 className="h-4 w-4 text-emerald" /> in use
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={busy === s.key}
                        disabled={busy !== null}
                        onClick={() => setConfirm(s)}
                      >
                        Activate
                      </Button>
                    )}
                  </div>
                );
              })}
              {!list && !error && (
                <p className="py-6 text-center text-sm text-white/40">Loading strategies…</p>
              )}
            </div>
          </Section>
        )}

        <Section title="Strategy validation">
          <div className="flex items-start gap-3 py-3 text-sm text-white/55">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" />
            <p>
              Every built-in strategy has been validated against historical data before shipping,
              and all of them run behind the same risk gates — quality score, exposure caps,
              correlation limits and the daily-loss circuit breaker are never bypassed, whichever
              strategy is active. Live trading stays locked; switching affects paper execution only.
            </p>
          </div>
        </Section>
      </div>

      <ConfirmDialog
        open={confirm !== null}
        title={confirm ? `Switch the engine to ${confirm.label}?` : ""}
        description="The running engine restarts on the new strategy immediately (paper mode) and the choice persists across restarts. Open positions are kept and managed to their stops/targets."
        confirmLabel="Activate"
        onConfirm={() => {
          if (confirm) void activate(confirm);
        }}
        onClose={() => setConfirm(null)}
      />
    </>
  );
}
