import {
  LayoutDashboard, User, BadgeCheck, ShieldCheck, Bell, SlidersHorizontal, Plug,
  Layers, ShieldAlert, BrainCircuit, Bot, CalendarClock, Wallet, KeyRound, Blocks,
  Users, CreditCard, Gauge, ScrollText, History, DatabaseBackup, Palette, Globe,
  FileLock2, Wrench, TriangleAlert, type LucideIcon,
} from "lucide-react";

export interface NavItem {
  slug: string;
  label: string;
  icon: LucideIcon;
  badge?: string;
  danger?: boolean;
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

export const SETTINGS_NAV: NavGroup[] = [
  {
    title: "Account",
    items: [
      { slug: "overview", label: "Overview", icon: LayoutDashboard },
      { slug: "profile", label: "Profile", icon: User },
      { slug: "account", label: "Account", icon: BadgeCheck },
      { slug: "security", label: "Security", icon: ShieldCheck },
      { slug: "notifications", label: "Notifications", icon: Bell },
    ],
  },
  {
    title: "Trading",
    items: [
      { slug: "trading", label: "Trading Preferences", icon: SlidersHorizontal },
      { slug: "exchanges", label: "Exchange Connections", icon: Plug },
      { slug: "strategies", label: "Strategies", icon: Layers },
      { slug: "risk", label: "Risk Management", icon: ShieldAlert },
      { slug: "ai", label: "AI Configuration", icon: BrainCircuit },
      { slug: "automation", label: "Automation", icon: Bot },
      { slug: "scheduler", label: "Scheduler", icon: CalendarClock },
      { slug: "portfolio", label: "Portfolio", icon: Wallet },
    ],
  },
  {
    title: "Developer",
    items: [
      { slug: "api-keys", label: "API Keys", icon: KeyRound },
      { slug: "integrations", label: "Integrations", icon: Blocks },
    ],
  },
  {
    title: "Workspace",
    items: [
      { slug: "team", label: "Team", icon: Users, badge: "Soon" },
      { slug: "billing", label: "Billing", icon: CreditCard },
      { slug: "usage", label: "Usage", icon: Gauge },
    ],
  },
  {
    title: "Records",
    items: [
      { slug: "logs", label: "Logs", icon: ScrollText },
      { slug: "audit", label: "Audit History", icon: History },
      { slug: "backup", label: "Backup & Restore", icon: DatabaseBackup },
    ],
  },
  {
    title: "Preferences",
    items: [
      { slug: "appearance", label: "Appearance", icon: Palette },
      { slug: "region", label: "Language & Region", icon: Globe },
      { slug: "privacy", label: "Data & Privacy", icon: FileLock2 },
      { slug: "advanced", label: "Advanced", icon: Wrench },
    ],
  },
  {
    title: "Danger",
    items: [{ slug: "danger", label: "Danger Zone", icon: TriangleAlert, danger: true }],
  },
];

export const ALL_ITEMS: NavItem[] = SETTINGS_NAV.flatMap((g) => g.items);
export const findItem = (slug: string) => ALL_ITEMS.find((i) => i.slug === slug);
