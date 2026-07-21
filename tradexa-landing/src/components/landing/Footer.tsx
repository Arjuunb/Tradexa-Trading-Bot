import { Github, MessageCircle } from "lucide-react";
import { Logo } from "@/components/Logo";
import { APP_URL, LOGIN_URL } from "@/lib/utils";

const GROUPS: { title: string; links: { label: string; href: string; external?: boolean }[] }[] = [
  {
    title: "Product",
    links: [
      { label: "Features", href: "#features" },
      { label: "How it works", href: "#how" },
      { label: "Performance", href: "#performance" },
      { label: "Launch Platform", href: APP_URL },
    ],
  },
  {
    title: "Developers",
    links: [
      { label: "Documentation", href: "#docs" },
      { label: "API", href: "#api" },
      { label: "GitHub", href: "https://github.com", external: true },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "Support", href: "#support" },
      { label: "Discord", href: "https://discord.com", external: true },
      { label: "Privacy", href: "#privacy" },
      { label: "Terms", href: "#terms" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="relative border-t border-line">
      <div className="container-x py-16">
        <div className="grid gap-12 lg:grid-cols-[1.4fr_2fr]">
          <div>
            <Logo />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-white/50">
              It remembers every trade, learns from every mistake, and builds a trading
              intelligence that’s yours alone — with full transparency over every decision.
            </p>
            <div className="mt-5 flex gap-2">
              <a
                href="https://github.com"
                target="_blank"
                rel="noreferrer"
                aria-label="GitHub"
                className="flex h-9 w-9 items-center justify-center rounded-lg border border-line text-white/60 transition hover:border-line-strong hover:text-white"
              >
                <Github className="h-4 w-4" />
              </a>
              <a
                href="https://discord.com"
                target="_blank"
                rel="noreferrer"
                aria-label="Discord"
                className="flex h-9 w-9 items-center justify-center rounded-lg border border-line text-white/60 transition hover:border-line-strong hover:text-white"
              >
                <MessageCircle className="h-4 w-4" />
              </a>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
            {GROUPS.map((g) => (
              <div key={g.title}>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/40">
                  {g.title}
                </p>
                <ul className="mt-4 space-y-2.5">
                  {g.links.map((l) => (
                    <li key={l.label}>
                      {l.external ? (
                        <a
                          href={l.href}
                          target="_blank"
                          rel="noreferrer"
                          className="text-sm text-white/60 transition hover:text-white"
                        >
                          {l.label}
                        </a>
                      ) : (
                        <a href={l.href} className="text-sm text-white/60 transition hover:text-white">
                          {l.label}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-14 flex flex-col items-center justify-between gap-4 border-t border-line pt-8 sm:flex-row">
          <p className="text-xs text-white/40">
            © {new Date().getFullYear()} TradeLogX Nexus. All rights reserved.
          </p>
          <div className="flex items-center gap-5 text-xs text-white/40">
            <a href={LOGIN_URL} className="hover:text-white">
              Sign in
            </a>
            <a href="#privacy" className="hover:text-white">
              Privacy
            </a>
            <a href="#terms" className="hover:text-white">
              Terms
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
