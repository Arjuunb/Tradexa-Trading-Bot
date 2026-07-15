import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Lock, ShieldCheck, ChevronDown } from "lucide-react";
import { SettingsHeader } from "@/components/settings/primitives";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";

interface Exchange {
  id: string;
  name: string;
  /** OKX/Coinbase/Kraken use an additional passphrase on their API keys. */
  passphrase: boolean;
}

interface Creds {
  apiKey: string;
  secret: string;
  passphrase: string;
}

const EXCHANGES: Exchange[] = [
  { id: "binance", name: "Binance", passphrase: false },
  { id: "bybit", name: "Bybit", passphrase: false },
  { id: "okx", name: "OKX", passphrase: true },
  { id: "hyperliquid", name: "Hyperliquid", passphrase: false },
  { id: "bitget", name: "Bitget", passphrase: false },
  { id: "coinbase", name: "Coinbase", passphrase: true },
  { id: "kraken", name: "Kraken", passphrase: true },
];

const EMPTY_CREDS: Creds = { apiKey: "", secret: "", passphrase: "" };

type BoolMap = Record<string, boolean>;
type CredsMap = Record<string, Creds>;

const initialBool = (): BoolMap =>
  Object.fromEntries(EXCHANGES.map((e) => [e.id, false]));
const initialCreds = (): CredsMap =>
  Object.fromEntries(EXCHANGES.map((e) => [e.id, { ...EMPTY_CREDS }]));

export default function Exchanges() {
  const { toast } = useToast();
  const [connected, setConnected] = useState<BoolMap>(initialBool);
  const [open, setOpen] = useState<BoolMap>(initialBool);
  const [creds, setCreds] = useState<CredsMap>(initialCreds);
  const [disconnectTarget, setDisconnectTarget] = useState<Exchange | null>(null);

  const setCred = (id: string, patch: Partial<Creds>) =>
    setCreds((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  const toggleForm = (id: string) =>
    setOpen((prev) => ({ ...prev, [id]: !prev[id] }));

  const testConnection = () =>
    toast("Connection test runs against the venue when the backend is connected.", "info");

  const save = (ex: Exchange) => {
    // Live trading is not wired yet — Tradexa runs in paper mode. Keys entered
    // here stay in this browser session only; they are NOT stored or transmitted.
    setConnected((prev) => ({ ...prev, [ex.id]: true }));
    setOpen((prev) => ({ ...prev, [ex.id]: false }));
    toast(`${ex.name} noted for this session — live trading isn't enabled yet, so nothing is stored or sent.`, "info");
  };

  const disconnect = (ex: Exchange) => {
    setConnected((prev) => ({ ...prev, [ex.id]: false }));
    setCreds((prev) => ({ ...prev, [ex.id]: { ...EMPTY_CREDS } }));
    setOpen((prev) => ({ ...prev, [ex.id]: false }));
    toast(`${ex.name} disconnected.`, "success");
  };

  return (
    <>
      <SettingsHeader
        title="Exchange Connections"
        description="Link your exchange accounts with API keys. Tradexa trades on your behalf — it never holds your funds."
      />

      <div className="mb-4 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-[13px] text-white/60">
        <b className="text-white/80">Preview.</b> Exchange connections aren’t wired to the engine yet —
        Tradexa runs in <b>paper mode</b>. Keys entered here are not stored or transmitted; live execution
        is a future release.
      </div>

      <div className="mb-5 flex items-start gap-3 rounded-xl border border-gold/30 bg-gold/[0.07] px-4 py-3.5">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-gold/30 bg-gold/10 text-gold">
          <Lock className="h-4 w-4" />
        </span>
        <div className="min-w-0 text-sm">
          <p className="font-medium text-white/90">
            Tradexa only needs trade permissions. NEVER enable withdrawal permissions on your API keys.
          </p>
          <p className="mt-0.5 text-[13px] text-white/55">Tradexa runs in paper mode and never holds your funds.</p>
        </div>
      </div>

      <div className="space-y-4">
        {EXCHANGES.map((ex) => {
          const isConnected = connected[ex.id];
          const isOpen = open[ex.id];
          const c = creds[ex.id];
          return (
            <Card key={ex.id} className="p-0">
              <div className="flex items-center justify-between gap-4 px-5 py-4 sm:px-6">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-line bg-ink-700 text-sm font-bold text-white/80">
                    {ex.name.slice(0, 2).toUpperCase()}
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-[15px] font-semibold text-white">{ex.name}</h3>
                    <p className="mt-0.5 flex items-center gap-1.5 text-[13px] text-white/45">
                      <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
                      Use trade-only keys with withdrawals disabled.
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <Badge tone={isConnected ? "emerald" : "neutral"}>
                    {isConnected ? "Connected" : "Not connected"}
                  </Badge>
                  {isConnected ? (
                    <Button size="sm" variant="secondary" onClick={() => toggleForm(ex.id)}>
                      Reconnect
                    </Button>
                  ) : (
                    <Button size="sm" onClick={() => toggleForm(ex.id)}>
                      <span className="inline-flex items-center gap-1.5">
                        Connect
                        <ChevronDown
                          className={cn("h-3.5 w-3.5 transition-transform", isOpen && "rotate-180")}
                        />
                      </span>
                    </Button>
                  )}
                </div>
              </div>

              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.22 }}
                    className="overflow-hidden border-t border-line"
                  >
                    <div className="space-y-4 px-5 py-5 sm:px-6">
                      <div className="grid gap-4 sm:grid-cols-2">
                        <Field label="API Key" htmlFor={`${ex.id}-key`}>
                          <Input
                            id={`${ex.id}-key`}
                            value={c.apiKey}
                            onChange={(e) => setCred(ex.id, { apiKey: e.target.value })}
                            placeholder="Paste your API key"
                            autoComplete="off"
                          />
                        </Field>
                        <Field label="Secret" htmlFor={`${ex.id}-secret`}>
                          <Input
                            id={`${ex.id}-secret`}
                            type="password"
                            value={c.secret}
                            onChange={(e) => setCred(ex.id, { secret: e.target.value })}
                            placeholder="Paste your API secret"
                            autoComplete="off"
                          />
                        </Field>
                        {ex.passphrase && (
                          <Field label="Passphrase" htmlFor={`${ex.id}-pass`}>
                            <Input
                              id={`${ex.id}-pass`}
                              type="password"
                              value={c.passphrase}
                              onChange={(e) => setCred(ex.id, { passphrase: e.target.value })}
                              placeholder="If required"
                              autoComplete="off"
                            />
                          </Field>
                        )}
                      </div>

                      <p className="flex items-center gap-1.5 text-[13px] text-white/45">
                        <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-emerald-soft" />
                        Reminder: create trade-only keys with withdrawals disabled.
                      </p>

                      <div className="flex flex-wrap items-center justify-end gap-2.5">
                        <Button size="sm" variant="ghost" onClick={testConnection}>
                          Test connection
                        </Button>
                        {isConnected && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="border-loss/40 text-loss-soft hover:bg-loss/10"
                            onClick={() => setDisconnectTarget(ex)}
                          >
                            Disconnect
                          </Button>
                        )}
                        <Button size="sm" onClick={() => save(ex)}>
                          {isConnected ? "Reconnect" : "Save"}
                        </Button>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {isConnected && !isOpen && (
                <div className="flex items-center justify-end gap-2.5 border-t border-line px-5 py-3 sm:px-6">
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-loss/40 text-loss-soft hover:bg-loss/10"
                    onClick={() => setDisconnectTarget(ex)}
                  >
                    Disconnect
                  </Button>
                </div>
              )}
            </Card>
          );
        })}
      </div>

      <ConfirmDialog
        open={disconnectTarget !== null}
        title={disconnectTarget ? `Disconnect ${disconnectTarget.name}?` : "Disconnect exchange?"}
        description="Tradexa will stop trading on this venue and the stored keys will be removed. You can reconnect at any time."
        confirmLabel="Disconnect"
        danger
        onConfirm={() => {
          if (disconnectTarget) disconnect(disconnectTarget);
        }}
        onClose={() => setDisconnectTarget(null)}
      />
    </>
  );
}
