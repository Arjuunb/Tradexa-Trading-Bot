import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** Shimmer loading placeholder. */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-lg bg-white/[0.05]",
        "after:absolute after:inset-0 after:-translate-x-full after:animate-shimmer after:bg-gradient-to-r after:from-transparent after:via-white/[0.06] after:to-transparent",
        className,
      )}
      {...props}
    />
  );
}
