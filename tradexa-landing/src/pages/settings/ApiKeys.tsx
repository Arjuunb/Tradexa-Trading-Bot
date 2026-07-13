import { useState } from "react";
import { KeyRound, Plus, Copy, RefreshCw, Trash2, X, Webhook, Code2 } from "lucide-react";
import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Switch } from "@/components/ui/Switch";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/lib/toast";

interface ApiToken {
  id: string;
  name: string;
  createdAt: string;
  masked: string;
}

const MASKED_TOKEN = "txa_••••••••••••";
const MASKED_SECRET = "whsec_••••••••••••••••";

/** Client-side random-looking string. Purely local — never a real server token. */
function randomString(len: number): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let out = "";
  for (let i = 0; i < len; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return out;
}

export default function ApiKeys() {
  const { toast } = useToast();
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [seq, setSeq] = useState<number>(0);
  const [fresh, setFresh] = useState<{ name: string; token: string } | null>(null);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const [devAccess, setDevAccess] = useState<boolean>(false);
  const [secret, setSecret] = useState<string>(() => randomString(40));
  const [revealSecret, setRevealSecret] = useState<boolean>(false);

  const revokeTarget = tokens.find((t) => t.id === revokeId) ?? null;

  const generate = (): void => {
    const n = seq + 1;
    const name = `Token ${n}`;
    const item: ApiToken = {
      id: `local-${n}-${Date.now()}`,
      name,
      createdAt: new Date().toISOString().slice(0, 10),
      masked: MASKED_TOKEN,
    };
    setSeq(n);
    setTokens((list) => [item, ...list]);
    setFresh({ name, token: `txa_${randomString(32)}` });
    toast("Token generated locally — connect the backend to issue real tokens.", "info");
  };

  const rotate = (t: ApiToken): void => {
    setTokens((list) =>
      list.map((x) => (x.id === t.id ? { ...x, createdAt: new Date().toISOString().slice(0, 10) } : x)),
    );
    setFresh({ name: t.name, token: `txa_${randomString(32)}` });
    toast(`${t.name} rotated locally.`, "info");
  };

  const revoke = (): void => {
    if (!revokeTarget) return;
    setTokens((list) => list.filter((x) => x.id !== revokeTarget.id));
    if (fresh && fresh.name === revokeTarget.name) setFresh(null);
    toast(`${revokeTarget.name} revoked.`, "success");
  };

  const copy = (value: string): void => {
    void navigator.clipboard?.writeText(value);
    toast("Copied to clipboard.", "success");
  };

  const regenerateSecret = (): void => {
    setSecret(randomString(40));
    setRevealSecret(false);
    toast("Webhook secret regenerated locally.", "info");
  };

  return (
    <>
      <SettingsHeader
        title="API Keys"
        description="Programmatic access to your Tradexa deployment. Everything here is generated locally in your browser — connect the backend to issue real, revocable tokens."
      />

      <div className="space-y-5">
        <Section
          title="Personal access tokens"
          description="Use these to authenticate requests to the Tradexa API."
          action={
            <Button size="sm" onClick={generate}>
              <Plus className="h-4 w-4" /> Generate API token
            </Button>
          }
        >
          {fresh && (
            <div className="my-3 rounded-xl border border-gold/30 bg-gold/[0.06] p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <p className="text-[13px] font-medium text-gold-soft">
                  {fresh.name} — copy it now, it won't be shown again
                </p>
                <button
                  type="button"
                  onClick={() => setFresh(null)}
                  className="text-white/40 transition hover:text-white"
                  aria-label="Dismiss"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded-lg border border-line bg-ink-800/60 px-3 py-2 font-mono text-[13px] text-white">
                  {fresh.token}
                </code>
                <Button size="sm" variant="secondary" onClick={() => copy(fresh.token)}>
                  <Copy className="h-4 w-4" /> Copy
                </Button>
              </div>
              <p className="mt-2 text-[12px] text-white/40">
                Generated locally — connect the backend to issue real tokens.
              </p>
            </div>
          )}

          {tokens.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line-strong bg-ink-800/40 px-6 py-10 text-center">
              <span className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl border border-line bg-ink-700 text-white/50">
                <KeyRound className="h-5 w-5" />
              </span>
              <p className="text-sm font-medium text-white/80">No tokens yet</p>
              <p className="mt-1 max-w-sm text-[13px] leading-relaxed text-white/45">
                Generate a token to see the flow. These are local only until the Tradexa backend is
                connected.
              </p>
            </div>
          ) : (
            tokens.map((t) => (
              <div
                key={t.id}
                className="flex flex-col gap-3 border-b border-line/60 py-4 last:border-0 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white/85">{t.name}</span>
                    <Badge tone="neutral">Local</Badge>
                  </div>
                  <p className="mt-1 flex items-center gap-2 text-[13px] text-white/45">
                    <code className="font-mono text-white/55">{t.masked}</code>
                    <span>· created {t.createdAt}</span>
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Button size="sm" variant="ghost" onClick={() => rotate(t)}>
                    <RefreshCw className="h-4 w-4" /> Rotate
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setRevokeId(t.id)}>
                    <Trash2 className="h-4 w-4" /> Revoke
                  </Button>
                </div>
              </div>
            ))
          )}
        </Section>

        <Section
          title="Webhook secret"
          description="Tradexa signs every inbound webhook with this secret so your endpoint can verify the payload really came from your bot."
        >
          <SettingRow
            label="Signing secret"
            description={
              <span className="inline-flex items-center gap-1.5">
                <Webhook className="h-3.5 w-3.5" /> Set this value on your receiving endpoint to validate
                signatures.
              </span>
            }
            stacked
          >
            <div className="flex items-center gap-2">
              <Input
                readOnly
                value={revealSecret ? `whsec_${secret}` : MASKED_SECRET}
                className="font-mono"
              />
              <Button
                size="sm"
                variant="secondary"
                className="shrink-0"
                onClick={() => setRevealSecret((r) => !r)}
              >
                {revealSecret ? "Hide" : "Reveal"}
              </Button>
              <Button size="sm" variant="ghost" className="shrink-0" onClick={regenerateSecret}>
                <RefreshCw className="h-4 w-4" /> Regenerate
              </Button>
            </div>
          </SettingRow>
        </Section>

        <Section title="Developer access" description="Controls for building against the Tradexa API.">
          <SettingRow
            label="Enable developer API access"
            description={
              <span className="inline-flex items-center gap-1.5">
                <Code2 className="h-3.5 w-3.5" /> Exposes REST + webhook endpoints to tokens above.
                Enforced by the backend when connected.
              </span>
            }
          >
            <Switch
              label="Enable developer API access"
              checked={devAccess}
              onChange={(v) => {
                setDevAccess(v);
                toast(v ? "Developer access enabled locally." : "Developer access disabled locally.", "info");
              }}
            />
          </SettingRow>
          <div className="py-4 text-[13px] leading-relaxed text-white/45">
            Full API reference, rate limits and example requests live in the docs. Endpoints activate once
            <span className="text-white/60"> VITE_API_BASE</span> points at your running Tradexa backend.
          </div>
        </Section>
      </div>

      <ConfirmDialog
        open={revokeId !== null}
        title="Revoke token"
        description={`Revoking ${revokeTarget?.name ?? "this token"} immediately disables it. Any client using it will stop working.`}
        confirmLabel="Revoke token"
        danger
        onConfirm={revoke}
        onClose={() => setRevokeId(null)}
      />
    </>
  );
}
