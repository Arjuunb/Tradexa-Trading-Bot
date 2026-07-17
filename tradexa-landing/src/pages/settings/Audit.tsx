import { useState } from "react";
import { Download, History } from "lucide-react";
import { SettingsHeader, Section, NotConnected } from "@/components/settings/primitives";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/lib/toast";

const TRACKED = [
  "Password changes", "Strategy edits", "Exchange added", "Bot started", "Bot stopped",
  "Risk changes", "API changes", "User logins",
];

const FILTERS = [
  { value: "all", label: "All actions" },
  { value: "security", label: "Security" },
  { value: "trading", label: "Trading" },
  { value: "api", label: "API" },
  { value: "auth", label: "Authentication" },
];

export default function Audit() {
  const { toast } = useToast();
  const [filter, setFilter] = useState("all");

  return (
    <>
      <SettingsHeader title="Audit History" description="A tamper-evident trail of every important action on your account." />

      <Section
        title="Activity"
        description="Filter and export your audit trail."
        action={
          <Button size="sm" variant="secondary" onClick={() => toast("Audit export runs when connected to the backend.", "info")}>
            <Download className="h-3.5 w-3.5" /> Export
          </Button>
        }
      >
        <div className="flex flex-wrap items-center gap-2 py-3">
          <div className="w-48">
            <Select value={filter} options={FILTERS} onChange={(e) => setFilter(e.target.value)} />
          </div>
        </div>
        <div className="pb-3">
          <NotConnected icon={History} detail="Your audit trail appears here once connected to the TradeLogX Nexus backend (VITE_API_BASE). Entries are never fabricated." />
        </div>
      </Section>

      <div className="mt-5">
        <Section title="Tracked actions" description="Everything TradeLogX Nexus records to the audit log.">
          <div className="flex flex-wrap gap-2 py-4">
            {TRACKED.map((t) => (
              <Badge key={t} tone="neutral">{t}</Badge>
            ))}
          </div>
        </Section>
      </div>
    </>
  );
}
