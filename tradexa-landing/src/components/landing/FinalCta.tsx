import { ArrowRight, ShieldCheck, Eye, Ban } from "lucide-react";
import { Reveal } from "@/components/Reveal";
import { Button } from "@/components/ui/Button";
import { BrainScanner } from "./BrainScanner";
import { APP_URL, SIGNUP_URL } from "@/lib/utils";

const ASSURANCES = [
  { icon: Eye, text: "Every decision is scored, explained and journaled" },
  { icon: ShieldCheck, text: "Risk guards are enforced — never bypassed" },
  { icon: Ban, text: "Trade-only API keys · withdrawals impossible" },
];

/** Closing section: the Decision Engine scanner (the page's third signature
 *  animation) beside the final call to action. */
export function FinalCta() {
  return (
    <section id="cta" className="section">
      <div className="container-x">
        <div className="surface relative overflow-hidden px-6 py-14 sm:px-12">
          <div className="pointer-events-none absolute inset-0 bg-radial-fade" />
          <div className="relative grid items-center gap-12 lg:grid-cols-[1fr_1.05fr]">
            <Reveal>
              <span className="eyebrow">Watch it think</span>
              <h2 className="mt-4 text-balance text-3xl font-bold tracking-tight text-white sm:text-4xl">
                A brain that says <span className="text-emerald-soft">yes</span> —{" "}
                and knows when to say <span className="text-loss-soft">no</span>.
              </h2>
              <p className="mt-4 max-w-md text-white/55">
                The Decision Engine scores every setup before a cent moves. Weak setups are
                skipped, strong ones execute — and either way it’s remembered, so the next
                decision starts smarter.
              </p>

              <ul className="mt-6 space-y-2.5">
                {ASSURANCES.map((a) => (
                  <li key={a.text} className="flex items-center gap-2.5 text-sm text-white/65">
                    <a.icon className="h-4 w-4 shrink-0 text-gold" />
                    {a.text}
                  </li>
                ))}
              </ul>

              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <a href={APP_URL}>
                  <Button size="lg" className="group">
                    Launch Platform
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </Button>
                </a>
                <a href={SIGNUP_URL}>
                  <Button size="lg" variant="secondary">
                    Create free account
                  </Button>
                </a>
              </div>
            </Reveal>

            <Reveal delay={0.15}>
              <BrainScanner />
              <p className="mt-3 px-1 font-mono text-[11px] leading-relaxed text-white/35">
                // looping demo of the evaluation pipeline · not live market data
              </p>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}
