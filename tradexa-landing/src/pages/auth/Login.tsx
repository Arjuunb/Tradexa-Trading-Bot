import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Mail, Lock } from "lucide-react";
import { AuthShell } from "@/components/auth/AuthShell";
import { SocialButtons } from "@/components/auth/SocialButtons";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Field } from "@/components/ui/Field";
import { Checkbox } from "@/components/ui/Checkbox";
import { loginSchema, type LoginValues } from "@/lib/validation";
import { auth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { APP_URL } from "@/lib/utils";

export default function Login() {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema), mode: "onBlur" });

  const onSubmit = async (values: LoginValues) => {
    setSubmitting(true);
    const res = await auth.signIn(values.email, values.password, values.remember ?? false);
    setSubmitting(false);
    if (!res.ok) return toast(res.message, "error");
    toast(res.message, res.demo ? "info" : "success");
    if (!res.demo) window.location.assign(APP_URL);
    else navigate("/auth/two-factor");
  };

  return (
    <AuthShell>
      <div className="mb-8 hidden lg:block">
        <Logo />
      </div>

      <h1 className="text-2xl font-bold tracking-tight text-white">Welcome back</h1>
      <p className="mt-1.5 text-sm text-white/50">Sign in to your Tradexa Trading Bot workspace.</p>

      <form onSubmit={handleSubmit(onSubmit)} className="mt-7 space-y-4" noValidate>
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

        <Field
          label="Password"
          htmlFor="password"
          error={errors.password?.message}
          hint={
            <Link to="/auth/forgot-password" className="text-xs text-gold/80 hover:text-gold">
              Forgot password?
            </Link>
          }
        >
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            placeholder="••••••••"
            icon={<Lock className="h-4 w-4" />}
            invalid={!!errors.password}
            {...register("password")}
          />
        </Field>

        <Checkbox id="remember" label="Remember me for 30 days" {...register("remember")} />

        <Button type="submit" fullWidth size="lg" loading={submitting}>
          Sign in
        </Button>
      </form>

      <div className="my-6 flex items-center gap-3">
        <span className="h-px flex-1 bg-line" />
        <span className="text-xs text-white/35">or continue with</span>
        <span className="h-px flex-1 bg-line" />
      </div>

      <SocialButtons />

      <p className="mt-8 text-center text-sm text-white/50">
        Don&apos;t have an account?{" "}
        <Link to="/auth/register" className="font-medium text-gold hover:text-gold-soft">
          Create account
        </Link>
      </p>
    </AuthShell>
  );
}
