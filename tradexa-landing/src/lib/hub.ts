/**
 * Runtime config injected by the backend when this SPA is served single-origin
 * to a SIGNED-IN operator (see automation-hub/app.py::_serve_landing). Anonymous
 * visitors never receive it — pages that drive the live engine must degrade to
 * an honest "sign in" state when this returns null.
 */
export interface HubConfig {
  apiBase: string;
  secret: string;
}

export function hubConfig(): HubConfig | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { __HUB_CONFIG__?: HubConfig };
  return w.__HUB_CONFIG__ ?? null;
}

/** Call a hub API endpoint with the operator's control secret. */
export async function hubFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const cfg = hubConfig();
  if (!cfg) throw new Error("Not signed in");
  const res = await fetch(`${cfg.apiBase}${path}`, {
    ...init,
    headers: {
      "X-Webhook-Secret": cfg.secret,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) throw new Error(`${init?.method ?? "GET"} ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}
