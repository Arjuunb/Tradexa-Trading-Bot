import { useState } from "react";
import { KeyRound, LogOut, Monitor, ScrollText, ShieldCheck } from "lucide-react";
import { SettingsHeader, Section, SettingRow, FieldStack, NotConnected } from "@/components/settings/primitives";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { hubConfig } from "@/lib/hub";
import { useToast } from "@/lib/toast";

export default function Security() {
  const { toast } = useToast();
  const signedIn = hubConfig() !== null;

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const [twoFactor, setTwoFactor] = useState(false);
  const [securityAlerts, setSecurityAlerts] = useState(true);

  const [logoutOpen, setLogoutOpen] = useState(false);

  const changePassword = async () => {
    if (!current || !next || !confirm) {
      toast("Fill in all password fields.", "error");
      return;
    }
    if (next !== confirm) {
      toast("New passwords do not match.", "error");
      return;
    }
    if (next.length < 8) {
      toast("New password must be at least 8 characters.", "error");
      return;
    }
    if (!signedIn) {
      toast("Sign in first — your password is managed by the hub account.", "error");
      return;
    }
    // Real change against the hub account (session-cookie authenticated).
    setBusy(true);
    try {
      const res = await fetch("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current, new: next }),
      });
      const body = (await res.json()) as { ok?: boolean; error?: string };
      if (!res.ok || !body.ok) {
        toast(body.error || "Password change failed.", "error");
        return;
      }
      setCurrent("");
      setNext("");
      setConfirm("");
      toast("Password changed.", "success");
    } catch {
      toast("Password change failed — backend unreachable.", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SettingsHeader
        title="Security"
        description="Protect your account with a strong password, two-factor authentication and session controls."
      />

      <div className="space-y-5">
        <Section title="Change password" description="Use a long, unique password.">
          <FieldStack className="sm:grid-cols-1">
            <Field label="Current password" htmlFor="currentPassword">
              <Input
                id="currentPassword"
                type="password"
                autoComplete="current-password"
                icon={<KeyRound className="h-4 w-4" />}
                placeholder="••••••••"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
            </Field>
            <Field label="New password" htmlFor="newPassword">
              <Input
                id="newPassword"
                type="password"
                autoComplete="new-password"
                placeholder="At least 8 characters"
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
            </Field>
            <Field label="Confirm new password" htmlFor="confirmPassword">
              <Input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                placeholder="Re-enter new password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </Field>
          </FieldStack>
          <div className="flex items-center justify-end gap-3 pb-3">
            {!signedIn && (
              <span className="text-[13px] text-white/40">
                Sign in to change your hub password.
              </span>
            )}
            <Button onClick={() => void changePassword()} loading={busy} disabled={!signedIn}>
              Update password
            </Button>
          </div>
        </Section>

        <Section title="Authentication" description="Extra verification when signing in.">
          <SettingRow
            label="Two-factor authentication"
            description="Require a time-based code from an authenticator app in addition to your password."
          >
            <div className="flex items-center gap-3 sm:justify-end">
              {twoFactor && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => toast("Recovery codes are available once 2FA is set up on the backend.", "info")}
                >
                  View recovery codes
                </Button>
              )}
              <Switch
                label="Two-factor authentication"
                checked={twoFactor}
                onChange={setTwoFactor}
              />
            </div>
          </SettingRow>
          <SettingRow
            label="Security notifications"
            description="Email me about new sign-ins, password changes and other security events."
          >
            <Switch
              label="Security notifications"
              checked={securityAlerts}
              onChange={setSecurityAlerts}
            />
          </SettingRow>
        </Section>

        <Section
          title="Sessions & devices"
          description="Where your account is currently signed in."
          action={
            <Button size="sm" variant="outline" onClick={() => setLogoutOpen(true)}>
              <LogOut className="h-3.5 w-3.5" /> Log out all devices
            </Button>
          }
        >
          <div className="space-y-4 py-3">
            <NotConnected
              icon={Monitor}
              detail="Session, device and login-history data appears here once connected to the Tradexa backend (VITE_API_BASE)."
            />
            <NotConnected
              icon={ShieldCheck}
              detail="Session, device and login-history data appears here once connected to the Tradexa backend (VITE_API_BASE)."
            />
          </div>
        </Section>

        <Section title="Login history" description="Recent sign-ins, failed attempts and IP history.">
          <div className="py-3">
            <NotConnected
              icon={ScrollText}
              detail="Session, device and login-history data appears here once connected to the Tradexa backend (VITE_API_BASE)."
            />
          </div>
        </Section>
      </div>

      <ConfirmDialog
        open={logoutOpen}
        title="Log out all devices"
        description="This signs you out of every active session on all devices. You'll need to sign in again everywhere."
        confirmLabel="Log out everywhere"
        onConfirm={() => toast("Signed out of all devices.", "success")}
        onClose={() => setLogoutOpen(false)}
      />
    </>
  );
}
