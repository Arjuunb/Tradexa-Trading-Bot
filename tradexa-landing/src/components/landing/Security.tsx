import { Lock, KeyRound, Ban, ServerCog, type LucideIcon } from "lucide-react";
import { Reveal } from "@/components/Reveal";
import { Card } from "@/components/ui/Card";

interface Item {
  icon: LucideIcon;
  title: string;
  body: string;
}

const ITEMS: Item[] = [
  { icon: Lock, title: "Military-grade encryption", body: "Data is encrypted in transit and at rest with industry-standard AES-256 and TLS." },
  { icon: KeyRound, title: "API keys encrypted", body: "Exchange keys are encrypted before storage and never exposed to the browser." },
  { icon: Ban, title: "No withdrawal permissions", body: "The bot trades only. It can never move or withdraw your funds — by design." },
  { icon: ServerCog, title: "Secure infrastructure", body: "Isolated, monitored infrastructure with least-privilege access and audit logging." },
];

export function Security() {
  return (
    <section id="security" className="section">
      <div className="container-x">
        <div className="grid items-center gap-14 lg:grid-cols-[1fr_1.1fr]">
          <div>
            <Reveal>
              <span className="eyebrow">Security</span>
              <h2 className="mt-4 text-balance text-3xl font-bold tracking-tight text-white sm:text-4xl">
                Built to be trusted with{" "}
                <span className="text-gold-gradient">your capital</span>
              </h2>
            </Reveal>
            <Reveal delay={0.1}>
              <p className="mt-4 max-w-md text-white/55">
                Automated trading only earns its place when the security is uncompromising. Tradexa
                is architected so the bot can execute — and nothing more.
              </p>
              <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-emerald/25 bg-emerald/[0.07] px-4 py-2 text-sm text-emerald-soft">
                <Ban className="h-4 w-4" />
                Trade-only keys · withdrawals impossible
              </div>
            </Reveal>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {ITEMS.map((it, i) => (
              <Reveal key={it.title} delay={i * 0.08}>
                <Card interactive className="h-full p-5">
                  <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line-strong bg-white/[0.04] text-gold">
                    <it.icon className="h-5 w-5" />
                  </div>
                  <h3 className="text-[15px] font-semibold text-white">{it.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-white/55">{it.body}</p>
                </Card>
              </Reveal>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
