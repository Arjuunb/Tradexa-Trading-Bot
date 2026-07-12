import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

/**
 * True when real Supabase credentials are present. When false, the auth layer
 * runs in DEMO mode: forms validate, animate and give honest feedback, but no
 * real account is created. Drop VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY into
 * the environment to go live — no code changes required.
 */
export const isSupabaseConfigured = Boolean(url && anonKey);

export const supabase: SupabaseClient | null = isSupabaseConfigured
  ? createClient(url as string, anonKey as string, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;
