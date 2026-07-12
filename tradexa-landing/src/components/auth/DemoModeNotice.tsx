import { Info } from "lucide-react";
import { auth } from "@/lib/auth";
import { cn } from "@/lib/utils";

/**
 * Honest banner shown only when Supabase is NOT configured, so nobody mistakes
 * the demo auth flow for a real account. Disappears automatically once real
 * credentials are supplied.
 */
export function DemoModeNotice({ className }: { className?: string }) {
  if (auth.configured) return null;
  return (
    <p
      className={cn(
        "flex items-start gap-2 rounded-lg border border-gold/20 bg-gold/[0.06] px-3 py-2 text-[11px] leading-relaxed text-gold-soft/90",
        className,
      )}
    >
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      Demo mode — forms validate and animate, but no real account is created. Add your Supabase keys
      to go live.
    </p>
  );
}
