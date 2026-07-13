import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { SettingsHeader } from "@/components/settings/primitives";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/lib/toast";

interface Action {
  id: string;
  title: string;
  desc: string;
  button: string;
  phrase?: string;
  run: (toast: (m: string, t?: "success" | "error" | "info") => void) => void;
}

const SETTINGS_KEY = "tradexa.settings.v1";

const ACTIONS: Action[] = [
  { id: "exchanges", title: "Disconnect all exchanges", desc: "Remove every stored API key and disconnect all venues.", button: "Disconnect all", run: (t) => t("All exchanges disconnected.", "success") },
  { id: "reset-bot", title: "Reset bot", desc: "Stop the engine and clear its in-memory state. Settings are kept.", button: "Reset bot", run: (t) => t("Bot reset.", "success") },
  { id: "strategies", title: "Delete all strategies", desc: "Permanently remove every strategy from your workspace.", button: "Delete strategies", run: (t) => t("All strategies deleted.", "success") },
  { id: "logs", title: "Delete all logs", desc: "Permanently erase system, trading and audit logs.", button: "Delete logs", run: (t) => t("All logs deleted.", "success") },
  { id: "account", title: "Delete account", desc: "Permanently delete your account and all associated data.", button: "Delete account", phrase: "DELETE", run: (t) => t("Account deletion requested.", "success") },
  {
    id: "factory",
    title: "Factory reset",
    desc: "Restore every setting to its default. This clears your saved configuration in this browser.",
    button: "Factory reset",
    phrase: "RESET",
    run: (t) => {
      try {
        localStorage.removeItem(SETTINGS_KEY);
        t("Factory reset complete. Reload to apply defaults.", "success");
      } catch {
        t("Reset failed — storage unavailable.", "error");
      }
    },
  },
];

export default function Danger() {
  const { toast } = useToast();
  const [active, setActive] = useState<Action | null>(null);

  return (
    <>
      <SettingsHeader title="Danger Zone" description="Irreversible and destructive actions. Please be certain." />

      <div className="mb-5 flex items-start gap-3 rounded-xl border border-loss/30 bg-loss/[0.06] px-4 py-3 text-sm text-loss-soft">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        These actions cannot be undone. Each requires explicit confirmation.
      </div>

      <div className="space-y-3">
        {ACTIONS.map((a) => (
          <div key={a.id} className="flex flex-col gap-3 rounded-xl border border-loss/25 bg-ink-700/50 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-white">{a.title}</p>
              <p className="mt-0.5 text-[13px] text-white/50">{a.desc}</p>
            </div>
            <Button
              className="shrink-0 bg-none bg-loss text-white shadow-none hover:brightness-110"
              onClick={() => setActive(a)}
            >
              {a.button}
            </Button>
          </div>
        ))}
      </div>

      <ConfirmDialog
        open={active !== null}
        danger
        title={active ? `${active.title}?` : ""}
        description={active?.desc ?? ""}
        confirmLabel={active?.button ?? "Confirm"}
        confirmPhrase={active?.phrase}
        onConfirm={() => active?.run(toast)}
        onClose={() => setActive(null)}
      />
    </>
  );
}
