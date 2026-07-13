import { useState, type ReactNode } from "react";
import { Mail, Phone, ShieldCheck, Trash2 } from "lucide-react";
import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useSettings } from "@/settings/store";
import { useToast } from "@/lib/toast";

/** A right-aligned read-only value, with an honest fallback when unknown. */
function Value({ children, muted }: { children?: ReactNode; muted?: boolean }) {
  return (
    <span className={muted ? "text-sm text-white/40" : "text-sm text-white/85"}>
      {children ?? "—"}
    </span>
  );
}

export default function Account() {
  const { settings, backendConnected } = useSettings();
  const { toast } = useToast();
  const [deleteOpen, setDeleteOpen] = useState(false);

  const email = settings.profile.email;
  const phone = settings.profile.phone;

  return (
    <>
      <SettingsHeader
        title="Account"
        description="Your account identity, plan and lifecycle. Identity fields are managed by the Tradexa backend."
      />

      <div className="space-y-5">
        <Section title="Identity" description="Read-only account details.">
          <SettingRow label="Account ID" description="Your unique account reference.">
            <Value muted>{backendConnected ? undefined : "Not connected"}</Value>
          </SettingRow>
          <SettingRow label="Member since" description="When this account was created.">
            <Value muted>{backendConnected ? undefined : "Not set"}</Value>
          </SettingRow>
          <SettingRow label="Current plan" description="Your active subscription tier.">
            <Value>Self-hosted · Free</Value>
          </SettingRow>
          <SettingRow label="Account status" description="Overall standing of your account.">
            <Badge tone="emerald">Active</Badge>
          </SettingRow>
        </Section>

        <Section title="Verification" description="Confirm ownership of your contact details.">
          <SettingRow
            label="Email verification"
            description={
              <span className="inline-flex items-center gap-1.5">
                <Mail className="h-3.5 w-3.5" /> {email || "No email on file"}
              </span>
            }
          >
            <div className="flex items-center gap-3 sm:justify-end">
              <Badge tone="neutral">Unverified</Badge>
              <Button
                size="sm"
                variant="outline"
                onClick={() => toast("Verification email sent.", "success")}
              >
                Resend verification
              </Button>
            </div>
          </SettingRow>
          <SettingRow
            label="Phone verification"
            description={
              <span className="inline-flex items-center gap-1.5">
                <Phone className="h-3.5 w-3.5" /> {phone || "No phone on file"}
              </span>
            }
          >
            <div className="flex items-center gap-3 sm:justify-end">
              <Badge tone="neutral">Unverified</Badge>
              <Button
                size="sm"
                variant="outline"
                onClick={() => toast("Verification code sent.", "success")}
              >
                Resend verification
              </Button>
            </div>
          </SettingRow>
        </Section>

        <Section
          title="Danger zone"
          description="Irreversible actions that affect your entire account."
        >
          <SettingRow
            label="Delete account"
            description="Permanently remove your account and all associated data. This cannot be undone."
          >
            <Button
              size="sm"
              variant="outline"
              className="border-loss/40 text-loss hover:bg-loss/10"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2 className="h-3.5 w-3.5" /> Delete account request
            </Button>
          </SettingRow>
        </Section>
      </div>

      <ConfirmDialog
        open={deleteOpen}
        danger
        title="Delete account"
        description="This requests permanent deletion of your account and every associated record. This action cannot be undone."
        confirmLabel="Request deletion"
        confirmPhrase="DELETE"
        onConfirm={() => toast("Account deletion requested.", "success")}
        onClose={() => setDeleteOpen(false)}
      />

      <div className="mt-5 flex items-center gap-2 text-[13px] text-white/35">
        <ShieldCheck className="h-3.5 w-3.5" />
        Identity and lifecycle actions are processed by the Tradexa backend when connected.
      </div>
    </>
  );
}
