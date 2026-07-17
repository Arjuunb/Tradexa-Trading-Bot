import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind class lists with conflict resolution (shadcn convention). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Where the "Launch Platform" CTA and post-auth redirect point (the running app). */
export const APP_URL = (import.meta.env.VITE_APP_URL as string | undefined) || "/app";

/** Format a number with fixed decimals + thousands separators (tabular UI). */
export function fmt(n: number, decimals = 0) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}
