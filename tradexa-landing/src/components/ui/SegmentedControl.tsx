import { cn } from "@/lib/utils";

interface Segment<T extends string> {
  value: T;
  label: string;
}

interface SegmentedControlProps<T extends string> {
  value: T;
  options: Segment<T>[];
  onChange: (value: T) => void;
  size?: "sm" | "md";
}

/** Compact single-select segmented control (e.g. theme, order type). */
export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  size = "md",
}: SegmentedControlProps<T>) {
  return (
    <div
      role="radiogroup"
      className={cn(
        "inline-flex rounded-xl border border-line bg-ink-800/60 p-1",
        size === "sm" && "p-0.5",
      )}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "rounded-lg font-medium transition-all",
              size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-[13px]",
              active
                ? "bg-white/[0.08] text-white shadow-sm"
                : "text-white/50 hover:text-white/80",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
