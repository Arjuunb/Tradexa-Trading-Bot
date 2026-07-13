import { useState } from "react";
import { Download, ScrollText, Search } from "lucide-react";
import { SettingsHeader, Section, NotConnected } from "@/components/settings/primitives";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/lib/toast";

const CATEGORIES: { value: string; label: string }[] = [
  { value: "all", label: "All logs" },
  { value: "system", label: "System logs" },
  { value: "trading", label: "Trading logs" },
  { value: "ai", label: "AI logs" },
  { value: "error", label: "Error logs" },
  { value: "exchange", label: "Exchange logs" },
  { value: "auth", label: "Authentication logs" },
];

export default function Logs() {
  const { toast } = useToast();
  const [query, setQuery] = useState<string>("");
  const [category, setCategory] = useState<string>("all");

  return (
    <>
      <SettingsHeader
        title="Logs"
        description="Inspect the engine's runtime log stream. Search, filter by category and export for support."
      />

      <Section
        title="Log viewer"
        description="Live logs are served by the Tradexa backend."
        action={
          <Button
            size="sm"
            variant="outline"
            onClick={() => toast("Log export runs once the backend is connected.", "info")}
          >
            <Download className="h-3.5 w-3.5" /> Export
          </Button>
        }
      >
        <div className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center">
          <div className="flex-1">
            <Input
              icon={<Search className="h-4 w-4" />}
              placeholder="Search log messages…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search logs"
            />
          </div>
          <div className="sm:w-56">
            <Select
              options={CATEGORIES}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              aria-label="Log category"
            />
          </div>
        </div>
        <div className="pb-3">
          <NotConnected
            icon={ScrollText}
            detail="Live logs stream here once VITE_API_BASE points at your running Tradexa backend."
          />
        </div>
      </Section>
    </>
  );
}
