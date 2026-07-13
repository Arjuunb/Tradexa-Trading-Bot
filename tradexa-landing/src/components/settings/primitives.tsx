import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { Plug } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/utils";

/** A titled settings group with optional description and header action. */
export function Section({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("p-0", className)}>
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4 sm:px-6">
        <div>
          <h3 className="text-[15px] font-semibold text-white">{title}</h3>
          {description && <p className="mt-0.5 text-sm text-white/50">{description}</p>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      <div className="px-5 py-2 sm:px-6">{children}</div>
    </Card>
  );
}

/** One labelled row inside a Section: label + description on the left, the
 *  control on the right. Stacks on mobile. */
export function SettingRow({
  label,
  htmlFor,
  description,
  children,
  stacked,
}: {
  label: string;
  htmlFor?: string;
  description?: ReactNode;
  children: ReactNode;
  stacked?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex gap-4 border-b border-line/60 py-4 last:border-0",
        stacked ? "flex-col" : "flex-col sm:flex-row sm:items-center sm:justify-between",
      )}
    >
      <div className="min-w-0 sm:max-w-[60%]">
        <label htmlFor={htmlFor} className="block text-sm font-medium text-white/85">
          {label}
        </label>
        {description && <p className="mt-0.5 text-[13px] leading-relaxed text-white/45">{description}</p>}
      </div>
      <div className={cn("shrink-0", stacked ? "w-full" : "sm:min-w-[200px] sm:text-right")}>
        {children}
      </div>
    </div>
  );
}

/** Page header for a settings section. */
export function SettingsHeader({ title, description }: { title: string; description: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="mb-6"
    >
      <h1 className="text-2xl font-bold tracking-tight text-white">{title}</h1>
      <p className="mt-1 text-sm text-white/50">{description}</p>
    </motion.div>
  );
}

/** Honest empty state for sections whose data lives on a backend that isn't
 *  wired in this deployment — never fabricates invoices, metrics or logs. */
export function NotConnected({
  title = "Backend not connected",
  detail,
  icon: Icon = Plug,
}: {
  title?: string;
  detail: string;
  icon?: typeof Plug;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line-strong bg-ink-800/40 px-6 py-12 text-center">
      <span className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl border border-line bg-ink-700 text-white/50">
        <Icon className="h-5 w-5" />
      </span>
      <p className="text-sm font-medium text-white/80">{title}</p>
      <p className="mt-1 max-w-sm text-[13px] leading-relaxed text-white/45">{detail}</p>
    </div>
  );
}

export function FieldStack({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("grid gap-4 py-3 sm:grid-cols-2", className)}>{children}</div>;
}
