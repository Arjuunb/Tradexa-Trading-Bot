import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Mail, Lock, User } from "lucide-react";
import { AuthShell } from "@/components/auth/AuthShell";
import { SocialButtons } from "@/components/auth/SocialButtons";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Field } from "@/components/ui/Field";
import { Checkbox } from "@/components/ui/Checkbox";
import { registerSchema, type RegisterValues, passwordStrength } from "@/lib/validation";
import { auth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";

const COUNTRIES = [
  "United States", "United Kingdom", "Canada", "Australia", "Germany", "France",
  "Netherlands", "Singapore", "United Arab Emirates", "India", "Japan", "Brazil", "Other",
];

const STRENGTH_COLORS = ["bg-white/15", "bg-loss", "bg-gold", "bg-emerald", "bg-emerald-soft"];

export default function Register() {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<RegisterValues>({ resolver: zodResolver(registerSchema), mode: "onBlur" });

  const pw = watch("password") ?? "";
  const strength = passwordStrength(pw);

  const onSubmit = async (values: RegisterValues) => {
    setSubmitting(true);
    const res = await auth.signUp(values);
    setSubmitting(false);
    if (!res.ok) return toast(res.message, "error");
    toast(res.message, res.demo ? "info" : "success");
    navigate("/auth/verify-email", { state: { email: values.email } });
  };

  return (
    <AuthShell>
      <div className="mb-8 hidden lg:block">
        <Logo />
      </div>

      <h1 className="text-2xl font-bold tracking-tight text-white">Create your account</h1>
      <p className="mt-1.5 text-sm text-white/50">Start automating in minutes. No card required.</p>

      <form onSubmit={handleSubmit(onSubmit)} className="mt-7 space-y-4" noValidate>
        <div className="grid grid-cols-2 gap-3">
          <Field label="First name" htmlFor="firstName" error={errors.firstName?.message}>
            <Input
              id="firstName"
              autoComplete="given-name"
              placeholder="Alex"
              icon={<User className="h-4 w-4" />}
              invalid={!!errors.firstName}
              {...register("firstName")}
            />
          </Field>
          <Field label="Last name" htmlFor="lastName" error={errors.lastName?.message}>
            <Input
              id="lastName"
              autoComplete="family-name"
              placeholder="Morgan"
              invalid={!!errors.lastName}
              {...register("lastName")}
            />
          </Field>
        </div>

        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            icon={<Mail className="h-4 w-4" />}
            invalid={!!errors.email}
            {...register("email")}
          />
        </Field>

        <Field label="Password" htmlFor="password" error={errors.password?.message}>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            placeholder="Create a strong password"
            icon={<Lock className="h-4 w-4" />}
            invalid={!!errors.password}
            {...register("password")}
          />
          {pw && (
            <div className="mt-2 flex items-center gap-2">
              <div className="flex flex-1 gap-1">
                {[0, 1, 2, 3].map((i) => (
                  <span
                    key={i}
                    className={cn(
                      "h-1 flex-1 rounded-full transition-colors",
                      i < strength.score ? STRENGTH_COLORS[strength.score] : "bg-white/10",
                    )}
                  />
                ))}
              </div>
              <span className="w-16 text-right text-[11px] text-white/45">{strength.label}</span>
            </div>
          )}
        </Field>

        <Field label="Confirm password" htmlFor="confirmPassword" error={errors.confirmPassword?.message}>
          <Input
            id="confirmPassword"
            type="password"
            autoComplete="new-password"
            placeholder="Re-enter your password"
            icon={<Lock className="h-4 w-4" />}
            invalid={!!errors.confirmPassword}
            {...register("confirmPassword")}
          />
        </Field>

        <Field label="Country" htmlFor="country" error={errors.country?.message}>
          <select
            id="country"
            defaultValue=""
            className={cn(
              "h-11 w-full rounded-xl border bg-ink-700/60 px-3.5 text-sm text-white outline-none transition-all",
              "focus:border-gold/50 focus:bg-ink-700/90 focus:ring-4 focus:ring-gold/10",
              errors.country ? "border-loss/60" : "border-line hover:border-line-strong",
            )}
            {...register("country")}
          >
            <option value="" disabled className="bg-ink-700">
              Select your country
            </option>
            {COUNTRIES.map((c) => (
              <option key={c} value={c} className="bg-ink-700">
                {c}
              </option>
            ))}
          </select>
        </Field>

        <div>
          <Checkbox
            id="acceptTerms"
            label="I agree to the Terms of Service and Privacy Policy"
            {...register("acceptTerms")}
          />
          {errors.acceptTerms && (
            <p className="mt-1.5 text-xs text-loss">{errors.acceptTerms.message}</p>
          )}
        </div>

        <Button type="submit" fullWidth size="lg" loading={submitting}>
          Create account
        </Button>
      </form>

      <div className="my-6 flex items-center gap-3">
        <span className="h-px flex-1 bg-line" />
        <span className="text-xs text-white/35">or sign up with</span>
        <span className="h-px flex-1 bg-line" />
      </div>

      <SocialButtons />

      <p className="mt-8 text-center text-sm text-white/50">
        Already have an account?{" "}
        <Link to="/auth/login" className="font-medium text-gold hover:text-gold-soft">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
