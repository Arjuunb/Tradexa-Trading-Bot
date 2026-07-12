import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** Hairline surface card with an optional interactive gold-glow hover. */
export function Card({
  className,
  interactive,
  ...props
}: HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cn(
        "surface relative overflow-hidden",
        interactive &&
          "transition-all duration-300 hover:border-line-strong hover:shadow-card hover:-translate-y-0.5",
        className,
      )}
      {...props}
    />
  );
}
