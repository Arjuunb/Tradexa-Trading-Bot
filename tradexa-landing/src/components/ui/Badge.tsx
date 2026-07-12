import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Tone = "gold" | "emerald" | "neutral" | "loss";

const TONES: Record<Tone, string> = {
  gold: "border-gold/30 bg-gold/10 text-gold-soft",
  emerald: "border-emerald/30 bg-emerald/10 text-emerald-soft",
  loss: "border-loss/30 bg-loss/10 text-loss-soft",
  neutral: "border-line-strong bg-white/[0.04] text-white/60",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}
