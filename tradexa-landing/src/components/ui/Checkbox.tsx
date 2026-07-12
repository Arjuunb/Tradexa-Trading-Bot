import { forwardRef, type InputHTMLAttributes } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: string;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, id, ...props }, ref) => {
    return (
      <label htmlFor={id} className="group inline-flex cursor-pointer select-none items-center gap-2.5">
        <span className="relative inline-flex h-[18px] w-[18px] items-center justify-center">
          <input
            ref={ref}
            id={id}
            type="checkbox"
            className="peer absolute inset-0 cursor-pointer opacity-0"
            {...props}
          />
          <span
            className={cn(
              "h-[18px] w-[18px] rounded-[6px] border border-line-strong bg-ink-700 transition-all",
              "peer-checked:border-gold peer-checked:bg-gold-sheen",
              "peer-focus-visible:ring-2 peer-focus-visible:ring-gold/60 peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-ink",
              className,
            )}
          />
          <Check className="pointer-events-none absolute h-3 w-3 scale-0 text-ink opacity-0 transition-all peer-checked:scale-100 peer-checked:opacity-100" />
        </span>
        {label && <span className="text-[13px] text-white/70">{label}</span>}
      </label>
    );
  },
);
Checkbox.displayName = "Checkbox";
