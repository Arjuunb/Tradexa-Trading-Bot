import { supabase, isSupabaseConfigured } from "./supabase";
import { APP_URL } from "./utils";

/**
 * Typed authentication service. Every method calls Supabase when it is
 * configured, and returns an honest DEMO result otherwise — so the UI is fully
 * functional to click through today and becomes live the moment real keys are
 * supplied. No fabricated sessions: demo mode always says so.
 */

export type OAuthProvider = "google" | "github";

export interface AuthResult {
  ok: boolean;
  demo: boolean;
  message: string;
}

const DEMO = (message: string): AuthResult => ({ ok: true, demo: true, message });
const FAIL = (message: string): AuthResult => ({ ok: false, demo: false, message });
const OK = (message: string): AuthResult => ({ ok: true, demo: false, message });

const redirectTo =
  typeof window !== "undefined" ? `${window.location.origin}/auth/reset-password` : undefined;

// Where the app lives after auth — VITE_APP_URL (e.g. the Render dashboard),
// resolved to an absolute URL for OAuth redirects. Falls back to <origin>/app.
const appUrl =
  typeof window !== "undefined"
    ? (APP_URL.startsWith("http") ? APP_URL : `${window.location.origin}${APP_URL}`)
    : undefined;

export interface SignUpInput {
  firstName: string;
  lastName: string;
  email: string;
  password: string;
  country: string;
}

export const auth = {
  configured: isSupabaseConfigured,

  async signIn(email: string, password: string, _remember: boolean): Promise<AuthResult> {
    if (!supabase) return DEMO("Demo mode — connect Supabase to sign in for real.");
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    return error ? FAIL(error.message) : OK("Signed in.");
  },

  async signUp(input: SignUpInput): Promise<AuthResult> {
    if (!supabase) return DEMO("Demo mode — connect Supabase to create an account.");
    const { error } = await supabase.auth.signUp({
      email: input.email,
      password: input.password,
      options: {
        data: {
          first_name: input.firstName,
          last_name: input.lastName,
          country: input.country,
        },
        emailRedirectTo:
          typeof window !== "undefined" ? `${window.location.origin}/auth/verify-email` : undefined,
      },
    });
    return error ? FAIL(error.message) : OK("Account created. Check your email to verify.");
  },

  async oauth(provider: OAuthProvider): Promise<AuthResult> {
    if (!supabase) return DEMO(`Demo mode — ${provider} sign-in needs Supabase configured.`);
    const { error } = await supabase.auth.signInWithOAuth({
      provider,
      options: {
        redirectTo: appUrl,
      },
    });
    return error ? FAIL(error.message) : OK(`Redirecting to ${provider}…`);
  },

  async forgotPassword(email: string): Promise<AuthResult> {
    if (!supabase) return DEMO("Demo mode — reset emails send once Supabase is connected.");
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo });
    return error ? FAIL(error.message) : OK("If that email exists, a reset link is on its way.");
  },

  async updatePassword(password: string): Promise<AuthResult> {
    if (!supabase) return DEMO("Demo mode — password updates apply once Supabase is connected.");
    const { error } = await supabase.auth.updateUser({ password });
    return error ? FAIL(error.message) : OK("Password updated. You can sign in now.");
  },

  async resendVerification(email: string): Promise<AuthResult> {
    if (!supabase) return DEMO("Demo mode — verification emails send once Supabase is connected.");
    const { error } = await supabase.auth.resend({ type: "signup", email });
    return error ? FAIL(error.message) : OK("Verification email resent.");
  },

  async verifyTotp(code: string): Promise<AuthResult> {
    if (!supabase) {
      return code.length === 6
        ? DEMO("Demo mode — 2FA verified locally. Connect Supabase MFA to enforce it.")
        : FAIL("Enter the full 6-digit code.");
    }
    // Real MFA: resolve the current challenge against the user's TOTP factor.
    const { data: factors, error: fErr } = await supabase.auth.mfa.listFactors();
    if (fErr) return FAIL(fErr.message);
    const totp = factors?.totp?.[0];
    if (!totp) return FAIL("No authenticator app is enrolled for this account.");
    const { data: ch, error: cErr } = await supabase.auth.mfa.challenge({ factorId: totp.id });
    if (cErr || !ch) return FAIL(cErr?.message || "Could not start the 2FA challenge.");
    const { error } = await supabase.auth.mfa.verify({
      factorId: totp.id,
      challengeId: ch.id,
      code,
    });
    return error ? FAIL(error.message) : OK("Two-factor verified.");
  },
};
