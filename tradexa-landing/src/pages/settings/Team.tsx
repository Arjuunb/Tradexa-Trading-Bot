import { Users } from "lucide-react";
import { SettingsHeader, Section, NotConnected } from "@/components/settings/primitives";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

const ROLES = [
  { name: "Owner", desc: "Full control, including billing and deletion." },
  { name: "Admin", desc: "Manage strategies, risk, exchanges and members." },
  { name: "Trader", desc: "Start/stop the bot and adjust trading settings." },
  { name: "Viewer", desc: "Read-only access to performance and logs." },
];

export default function Team() {
  return (
    <>
      <SettingsHeader title="Team" description="Invite teammates and manage roles across your workspace." />

      <div className="space-y-5">
        <Section
          title="Members"
          description="Multi-seat collaboration is on the roadmap."
          action={<Badge tone="neutral">Coming soon</Badge>}
        >
          <div className="py-3">
            <NotConnected icon={Users} title="Team management is coming soon" detail="Invite teammates, assign roles and control who can start the bot or change risk settings. This lands in a future release." />
          </div>
          <div className="border-t border-line/60 py-3">
            <Button disabled>Invite teammate</Button>
          </div>
        </Section>

        <Section title="Planned roles">
          <div className="divide-y divide-line/60">
            {ROLES.map((r) => (
              <div key={r.name} className="flex items-center gap-3 py-3">
                <Badge tone="gold">{r.name}</Badge>
                <p className="text-[13px] text-white/55">{r.desc}</p>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </>
  );
}
