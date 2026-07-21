import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind class lists with conflict resolution (shadcn convention). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Where the "Launch Platform" CTA and post-auth redirect point (the running app). */
export const APP_URL = (import.meta.env.VITE_APP_URL as string | undefined) || "/app";

/** Origin of the running app/backend (which owns the real sign-in). When APP_URL
 *  is a full URL we take its origin; when it's a same-origin path ("/app") the
 *  backend serves /login at the current origin. */
function _appOrigin(): string {
  try { return APP_URL.startsWith("http") ? new URL(APP_URL).origin : ""; }
  catch { return ""; }
}
/** The single real sign-in / create-account pages — served by the backend at its
 *  origin root (premium cookie-session auth). All landing CTAs point here so there
 *  is ONE front door, not a separate demo login. */
export const LOGIN_URL = `${_appOrigin()}/login`;
export const SIGNUP_URL = `${_appOrigin()}/signup`;

/** Format a number with fixed decimals + thousands separators (tabular UI). */
export function fmt(n: number, decimals = 0) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}
