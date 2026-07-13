import { NotebookText, LineChart, Send, Hash, Slack, HardDrive, FileText, Table2, Zap, Webhook, type LucideIcon } from "lucide-react";
import { SettingsHeader } from "@/components/settings/primitives";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/lib/toast";

interface Integration {
  name: string;
  desc: string;
  icon: LucideIcon;
  status: "available" | "off";
}

const ITEMS: Integration[] = [
  { name: "Tradexa Journal", desc: "Auto-send completed trades to your journal.", icon: NotebookText, status: "available" },
  { name: "TradingView", desc: "Receive alerts as webhook signals.", icon: LineChart, status: "off" },
  { name: "Telegram", desc: "Push alerts to a Telegram chat.", icon: Send, status: "off" },
  { name: "Discord", desc: "Push alerts to a Discord channel.", icon: Hash, status: "off" },
  { name: "Slack", desc: "Notify a Slack workspace.", icon: Slack, status: "off" },
  { name: "Google Drive", desc: "Back up configuration & exports.", icon: HardDrive, status: "off" },
  { name: "Notion", desc: "Sync reports to a Notion database.", icon: FileText, status: "off" },
  { name: "Google Sheets", desc: "Export trades to a spreadsheet.", icon: Table2, status: "off" },
  { name: "Zapier", desc: "Connect Tradexa to 6,000+ apps.", icon: Zap, status: "off" },
  { name: "Webhooks", desc: "POST events to your own endpoints.", icon: Webhook, status: "off" },
];

export default function Integrations() {
  const { toast } = useToast();
  return (
    <>
      <SettingsHeader title="Integrations" description="Connect Tradexa to the tools you already use." />
      <div className="grid gap-3 sm:grid-cols-2">
        {ITEMS.map((it) => (
          <Card key={it.name} className="flex items-start gap-3 p-4">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-line bg-ink-800/60 text-white/70">
              <it.icon className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold text-white">{it.name}</p>
                <Badge tone={it.status === "available" ? "gold" : "neutral"}>
                  {it.status === "available" ? "Available" : "Not connected"}
                </Badge>
              </div>
              <p className="mt-0.5 text-[13px] text-white/45">{it.desc}</p>
              <Button
                size="sm"
                variant="secondary"
                className="mt-3"
                onClick={() => toast(`Connect ${it.name} — available when the backend integration is enabled.`, "info")}
              >
                {it.status === "available" ? "Configure" : "Connect"}
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
