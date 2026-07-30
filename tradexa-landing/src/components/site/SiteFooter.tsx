import { Github, MessageCircle, ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { SITE_ROUTES, ACCENT_CLASSES } from "@/site/routes";
import { APP_URL, LOGIN_URL, cn } from "@/lib/utils";

const RESOURCES = [
  { label: "Documentation", href: "#docs" },
  { label: "API reference", href: "#api" },
  { label: "GitHub", href: "https://github.com", external: true },
  { label: "Discord", href: "https://discord.com", external: true },
];

const COMPANY = [
  { label: "Support", href: "#support" },
  { label: "Privacy", href: "#privacy" },
  { label: "Terms", href: "#terms" },
  { label: "Status", href: "#status" },
];

/**
 * Shared footer. The product column is generated from the route table rather
 * than hand-listed, so a new page appears here the moment it exists — and each
 * entry carries the destination's accent dot, which is the same visual cue the
 * navbar uses. The old footer pointed at hash fragments that only resolved on
 * the landing page; from /engine, "How it works" silently did nothing.
 */
export function SiteFooter() {
  return (
    <footer className="relative border-t border-line bg-black/40 backdrop-blur-sm">
      <div className="container-x py-16">
        <div className="grid gap-12 lg:grid-cols-[1.3fr_2fr]">
          <div>
            <Link to="/" aria-label="TradeLogX Nexus home">
              <Logo />
            </Link>
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

          <div className="grid gap-8 sm:grid-cols-3">
            <div className="sm:col-span-1">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/40">
                Platform
              </p>
              <ul className="mt-4 space-y-2.5">
                {SITE_ROUTES.map((r) => (
                  <li key={r.path}>
                    <Link
                      to={r.path}
                      className="group flex items-center gap-2 text-sm text-white/60 transition hover:text-white"
                    >
                      <span
                        className={cn(
                          "h-1.5 w-1.5 shrink-0 rounded-full opacity-60 transition-opacity group-hover:opacity-100",
                          ACCENT_CLASSES[r.accent].bg,
                        )}
                      />
                      {r.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/40">
                Developers
              </p>
              <ul className="mt-4 space-y-2.5">
                {RESOURCES.map((l) => (
                  <li key={l.label}>
                    <a
                      href={l.href}
                      {...(l.external ? { target: "_blank", rel: "noreferrer" } : {})}
                      className="group inline-flex items-center gap-1 text-sm text-white/60 transition hover:text-white"
                    >
                      {l.label}
                      {l.external && (
                        <ArrowUpRight className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-60" />
                      )}
                    </a>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/40">
                Company
              </p>
              <ul className="mt-4 space-y-2.5">
                {COMPANY.map((l) => (
                  <li key={l.label}>
                    <a href={l.href} className="text-sm text-white/60 transition hover:text-white">
                      {l.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
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
            <a href={APP_URL} className="hover:text-white">
              Launch Platform
            </a>
            <a href="#privacy" className="hover:text-white">
              Privacy
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
