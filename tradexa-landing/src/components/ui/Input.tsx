import { forwardRef, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";
import { cn } from "@/lib/utils";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: ReactNode;
  invalid?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, icon, invalid, type, ...props }, ref) => {
    const [reveal, setReveal] = useState(false);
    const isPassword = type === "password";
    const inputType = isPassword ? (reveal ? "text" : "password") : type;

    return (
      <div className="relative">
        {icon && (
          <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-white/40">
            {icon}
          </span>
        )}
        <input
          ref={ref}
          type={inputType}
          className={cn(
            "h-11 w-full rounded-xl border bg-ink-700/60 text-sm text-white placeholder:text-white/35",
            "transition-all duration-200 outline-none",
            "focus:border-gold/50 focus:bg-ink-700/90 focus:ring-4 focus:ring-gold/10",
            icon ? "pl-10 pr-3.5" : "px-3.5",
            isPassword && "pr-11",
            invalid
              ? "border-loss/60 focus:border-loss/70 focus:ring-loss/10"
              : "border-line hover:border-line-strong",
            className,
          )}
          {...props}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setReveal((r) => !r)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-white/40 transition hover:text-white/80"
            aria-label={reveal ? "Hide password" : "Show password"}
            tabIndex={-1}
          >
            {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        )}
      </div>
    );
  },
);
Input.displayName = "Input";
