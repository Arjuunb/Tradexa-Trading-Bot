import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, X } from "lucide-react";
import { Button } from "./Button";
import { Input } from "./Input";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  danger?: boolean;
  /** If set, the user must type this exact string to enable the confirm button. */
  confirmPhrase?: string;
  onConfirm: () => void | Promise<void>;
  onClose: () => void;
}

/** Accessible modal confirmation for destructive actions. Supports a
 *  "type-to-confirm" phrase gate for the most dangerous operations. */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  danger,
  confirmPhrase,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      setPhrase("");
      setBusy(false);
    }
  }, [open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const gated = Boolean(confirmPhrase) && phrase.trim() !== confirmPhrase;

  const run = async () => {
    setBusy(true);
    await onConfirm();
    setBusy(false);
    onClose();
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[120] flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            role="alertdialog"
            aria-modal="true"
            aria-label={title}
            initial={{ scale: 0.96, y: 12, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.96, y: 12, opacity: 0 }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
            className="glass-strong relative w-full max-w-md rounded-2xl p-6 shadow-card"
          >
            <button
              onClick={onClose}
              className="absolute right-4 top-4 text-white/40 transition hover:text-white"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
            <div className="flex items-start gap-3">
              <span
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${
                  danger ? "border-loss/30 bg-loss/10 text-loss" : "border-gold/30 bg-gold/10 text-gold"
                }`}
              >
                <AlertTriangle className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-white">{title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-white/60">{description}</p>
              </div>
            </div>

            {confirmPhrase && (
              <div className="mt-4">
                <p className="mb-1.5 text-xs text-white/50">
                  Type <span className="font-mono font-semibold text-white">{confirmPhrase}</span> to confirm
                </p>
                <Input value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder={confirmPhrase} />
              </div>
            )}

            <div className="mt-6 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant={danger ? "primary" : "primary"}
                className={danger ? "bg-none bg-loss text-white hover:brightness-110 shadow-none" : ""}
                loading={busy}
                disabled={gated}
                onClick={run}
              >
                {confirmLabel}
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
