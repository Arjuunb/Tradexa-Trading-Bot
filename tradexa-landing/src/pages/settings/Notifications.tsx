import { Mail, Smartphone, Monitor, MessageSquare, Send, Hash, Webhook } from "lucide-react";
import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Switch } from "@/components/ui/Switch";
import { useSettings } from "@/settings/store";

const CHANNELS: { key: keyof ReturnType<typeof channelKeys>; label: string; desc: string; icon: typeof Mail; soon?: boolean }[] = [
  { key: "email", label: "Email", desc: "Trade and system alerts to your inbox.", icon: Mail },
  { key: "push", label: "Push", desc: "Mobile push notifications.", icon: Smartphone },
  { key: "desktop", label: "Desktop", desc: "Browser desktop notifications.", icon: Monitor },
  { key: "sms", label: "SMS", desc: "Text-message alerts.", icon: MessageSquare, soon: true },
  { key: "telegram", label: "Telegram", desc: "Alerts to a Telegram chat.", icon: Send },
  { key: "discord", label: "Discord", desc: "Alerts to a Discord channel.", icon: Hash },
  { key: "webhook", label: "Webhook", desc: "POST events to your own endpoint.", icon: Webhook },
];
function channelKeys() {
  return { email: 0, push: 0, desktop: 0, sms: 0, telegram: 0, discord: 0, webhook: 0 };
}

const EVENTS: { key: keyof ReturnType<typeof eventKeys>; label: string; desc: string }[] = [
  { key: "botStarted", label: "Bot started", desc: "The engine begins scanning." },
  { key: "botStopped", label: "Bot stopped", desc: "The engine halts." },
  { key: "tradeOpened", label: "Trade opened", desc: "A position is entered." },
  { key: "tradeClosed", label: "Trade closed", desc: "A position is exited." },
  { key: "slHit", label: "Stop-loss hit", desc: "A stop is triggered." },
  { key: "tpHit", label: "Take-profit hit", desc: "A target is reached." },
  { key: "dailyReport", label: "Daily report", desc: "End-of-day performance digest." },
  { key: "weeklyReport", label: "Weekly report", desc: "Weekly summary." },
  { key: "monthlyReport", label: "Monthly report", desc: "Monthly summary." },
  { key: "systemErrors", label: "System errors", desc: "Internal failures." },
  { key: "exchangeErrors", label: "Exchange errors", desc: "Venue/connection issues." },
  { key: "apiErrors", label: "API errors", desc: "Rate limits or auth failures." },
];
function eventKeys() {
  return {
    botStarted: 0, botStopped: 0, tradeOpened: 0, tradeClosed: 0, slHit: 0, tpHit: 0,
    dailyReport: 0, weeklyReport: 0, monthlyReport: 0, systemErrors: 0, exchangeErrors: 0, apiErrors: 0,
  };
}

export default function Notifications() {
  const { settings, update } = useSettings();
  const n = settings.notifications;

  return (
    <>
      <SettingsHeader title="Notifications" description="Choose how and when Tradexa reaches you. Changes save automatically." />

      <div className="space-y-5">
        <Section title="Channels" description="Where notifications are delivered.">
          {CHANNELS.map((c) => (
            <SettingRow
              key={c.key}
              label={c.soon ? `${c.label} · Soon` : c.label}
              description={<span className="inline-flex items-center gap-1.5"><c.icon className="h-3.5 w-3.5" /> {c.desc}</span>}
            >
              <Switch
                label={c.label}
                checked={n.channels[c.key]}
                disabled={c.soon}
                onChange={(v) => update("notifications", { channels: { ...n.channels, [c.key]: v } })}
              />
            </SettingRow>
          ))}
        </Section>

        <Section title="Alert types" description="Which events trigger a notification.">
          {EVENTS.map((e) => (
            <SettingRow key={e.key} label={e.label} description={e.desc}>
              <Switch
                label={e.label}
                checked={n.events[e.key]}
                onChange={(v) => update("notifications", { events: { ...n.events, [e.key]: v } })}
              />
            </SettingRow>
          ))}
        </Section>
      </div>
    </>
  );
}
