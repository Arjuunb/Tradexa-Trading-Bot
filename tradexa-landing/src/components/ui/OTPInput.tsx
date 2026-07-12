import { useRef, type ClipboardEvent, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";

interface OTPInputProps {
  value: string;
  onChange: (value: string) => void;
  length?: number;
  invalid?: boolean;
}

/** Accessible 6-box one-time-code input with paste + arrow-key support. */
export function OTPInput({ value, onChange, length = 6, invalid }: OTPInputProps) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = value.split("").slice(0, length);

  const set = (i: number, d: string) => {
    const next = value.split("");
    next[i] = d;
    onChange(next.join("").slice(0, length));
  };

  const handleKey = (i: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace") {
      e.preventDefault();
      if (digits[i]) set(i, "");
      else if (i > 0) {
        refs.current[i - 1]?.focus();
        set(i - 1, "");
      }
    } else if (e.key === "ArrowLeft" && i > 0) refs.current[i - 1]?.focus();
    else if (e.key === "ArrowRight" && i < length - 1) refs.current[i + 1]?.focus();
  };

  const handlePaste = (e: ClipboardEvent) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, length);
    if (pasted) {
      onChange(pasted);
      refs.current[Math.min(pasted.length, length - 1)]?.focus();
    }
  };

  return (
    <div className="flex justify-center gap-2 sm:gap-3" onPaste={handlePaste}>
      {Array.from({ length }).map((_, i) => (
        <input
          key={i}
          ref={(el) => (refs.current[i] = el)}
          inputMode="numeric"
          maxLength={1}
          value={digits[i] ?? ""}
          aria-label={`Digit ${i + 1}`}
          onChange={(e) => {
            const d = e.target.value.replace(/\D/g, "").slice(-1);
            if (d) {
              set(i, d);
              if (i < length - 1) refs.current[i + 1]?.focus();
            }
          }}
          onKeyDown={(e) => handleKey(i, e)}
          className={cn(
            "h-14 w-11 rounded-xl border bg-ink-700/70 text-center font-mono text-xl text-white outline-none transition-all sm:w-12",
            "focus:border-gold/60 focus:bg-ink-700 focus:ring-4 focus:ring-gold/10",
            invalid ? "border-loss/60" : "border-line hover:border-line-strong",
          )}
        />
      ))}
    </div>
  );
}
