import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { auth, type OAuthProvider } from "@/lib/auth";
import { useToast } from "@/lib/toast";

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M12 10.2v3.9h5.5c-.24 1.4-1.6 4.1-5.5 4.1-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.9 1.5l2.7-2.6C16.9 3.5 14.7 2.5 12 2.5 6.9 2.5 2.8 6.6 2.8 12S6.9 21.5 12 21.5c5.6 0 9.3-3.9 9.3-9.5 0-.6-.06-1-.16-1.8H12z"
      />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 fill-white" aria-hidden="true">
      <path d="M12 2C6.48 2 2 6.58 2 12.25c0 4.53 2.87 8.37 6.84 9.73.5.1.68-.22.68-.49l-.01-1.7c-2.78.62-3.37-1.37-3.37-1.37-.46-1.18-1.11-1.5-1.11-1.5-.9-.63.07-.62.07-.62 1 .07 1.53 1.06 1.53 1.06.89 1.56 2.34 1.11 2.91.85.09-.66.35-1.11.63-1.36-2.22-.26-4.56-1.14-4.56-5.06 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.28 2.75 1.05a9.3 9.3 0 015 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.41.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.93-2.35 4.79-4.58 5.05.36.32.68.94.68 1.9l-.01 2.82c0 .27.18.6.69.49A10.02 10.02 0 0022 12.25C22 6.58 17.52 2 12 2z" />
    </svg>
  );
}

/** Google + GitHub OAuth buttons wired to the auth service. */
export function SocialButtons() {
  const { toast } = useToast();
  const [busy, setBusy] = useState<OAuthProvider | null>(null);

  const go = async (provider: OAuthProvider) => {
    setBusy(provider);
    const res = await auth.oauth(provider);
    if (!res.ok) toast(res.message, "error");
    else if (res.demo) toast(res.message, "info");
    setBusy(null);
  };

  return (
    <div className="grid grid-cols-2 gap-3">
      <Button variant="outline" onClick={() => go("google")} loading={busy === "google"} type="button">
        {busy !== "google" && <GoogleIcon />}
        Google
      </Button>
      <Button variant="outline" onClick={() => go("github")} loading={busy === "github"} type="button">
        {busy !== "github" && <GitHubIcon />}
        GitHub
      </Button>
    </div>
  );
}
