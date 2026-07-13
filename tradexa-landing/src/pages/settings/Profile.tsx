import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Camera, Mail, Phone, User } from "lucide-react";
import { SettingsHeader, Section, FieldStack } from "@/components/settings/primitives";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { profileSchema } from "@/settings/schema";
import { useSettings } from "@/settings/store";
import { useToast } from "@/lib/toast";
import type { z } from "zod";

type Values = z.infer<typeof profileSchema>;

const COUNTRIES = ["United States", "United Kingdom", "Canada", "Germany", "Singapore", "United Arab Emirates", "India", "Japan", "Australia", "Other"];
const TIMEZONES = ["UTC", "America/New_York", "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Asia/Singapore", "Asia/Tokyo", "Asia/Dubai"];
const LANGS = [["en", "English"], ["es", "Español"], ["de", "Deutsch"], ["fr", "Français"], ["ja", "日本語"], ["zh", "中文"]];
const EXPERIENCE = [["beginner", "Beginner"], ["intermediate", "Intermediate"], ["advanced", "Advanced"], ["professional", "Professional"]];

export default function Profile() {
  const { settings, setSection } = useSettings();
  const { toast } = useToast();
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isDirty },
    reset,
  } = useForm<Values>({ resolver: zodResolver(profileSchema), defaultValues: settings.profile });

  const initials = (watch("fullName") || watch("username") || "T A")
    .split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase();

  const onSubmit = (values: Values) => {
    setSection("profile", values);
    reset(values);
    toast("Profile updated", "success");
  };

  return (
    <>
      <SettingsHeader title="Profile" description="Your personal information and how you appear across Tradexa." />

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
        <Section title="Profile picture" description="PNG or JPG, up to 2MB.">
          <div className="flex items-center gap-5 py-3">
            <div className="relative">
              <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-gold-sheen text-2xl font-bold text-ink">
                {initials || "TA"}
              </div>
              <button
                type="button"
                onClick={() => toast("Avatar upload connects to storage when configured.", "info")}
                className="absolute -bottom-1.5 -right-1.5 flex h-7 w-7 items-center justify-center rounded-lg border border-line-strong bg-ink-700 text-white/70 transition hover:text-white"
                aria-label="Change picture"
              >
                <Camera className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="text-sm text-white/50">
              <p>Upload a new avatar.</p>
              <p className="text-[13px] text-white/35">Stored securely when object storage is connected.</p>
            </div>
          </div>
        </Section>

        <Section title="Personal information">
          <FieldStack>
            <Field label="Full name" htmlFor="fullName" error={errors.fullName?.message}>
              <Input id="fullName" icon={<User className="h-4 w-4" />} placeholder="Alex Morgan" {...register("fullName")} />
            </Field>
            <Field label="Username" htmlFor="username" error={errors.username?.message}>
              <Input id="username" placeholder="alexmorgan" {...register("username")} />
            </Field>
            <Field label="Email" htmlFor="email" error={errors.email?.message}>
              <Input id="email" type="email" icon={<Mail className="h-4 w-4" />} placeholder="you@company.com" {...register("email")} />
            </Field>
            <Field label="Phone number" htmlFor="phone" error={errors.phone?.message}>
              <Input id="phone" icon={<Phone className="h-4 w-4" />} placeholder="+1 555 000 0000" {...register("phone")} />
            </Field>
            <Field label="Country" htmlFor="country">
              <Select id="country" options={[{ value: "", label: "Select country" }, ...COUNTRIES.map((c) => ({ value: c, label: c }))]} {...register("country")} />
            </Field>
            <Field label="Timezone" htmlFor="timezone">
              <Select id="timezone" options={TIMEZONES.map((t) => ({ value: t, label: t }))} {...register("timezone")} />
            </Field>
            <Field label="Language" htmlFor="language">
              <Select id="language" options={LANGS.map(([v, l]) => ({ value: v, label: l }))} {...register("language")} />
            </Field>
            <Field label="Trading experience" htmlFor="experience">
              <Select id="experience" options={EXPERIENCE.map(([v, l]) => ({ value: v, label: l }))} {...register("experience")} />
            </Field>
          </FieldStack>
          <div className="pb-3">
            <Field label="Bio" htmlFor="bio" error={errors.bio?.message}>
              <textarea
                id="bio"
                rows={3}
                placeholder="A short line about how you trade."
                className="w-full rounded-xl border border-line bg-ink-700/60 px-3.5 py-2.5 text-sm text-white outline-none transition-all placeholder:text-white/35 focus:border-gold/50 focus:ring-4 focus:ring-gold/10"
                {...register("bio")}
              />
            </Field>
          </div>
        </Section>

        <div className="flex items-center justify-end gap-3">
          <Button type="button" variant="ghost" disabled={!isDirty} onClick={() => reset(settings.profile)}>
            Discard
          </Button>
          <Button type="submit" disabled={!isDirty}>
            Save changes
          </Button>
        </div>
      </form>
    </>
  );
}
