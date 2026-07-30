import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { FileText, Printer } from "lucide-react";
import { LegalBackdrop } from "@/components/site/backdrops";
import { prefetchRoute } from "@/site/routes";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

const LEGAL_PAGES = [
  { path: "/privacy", label: "Privacy policy" },
  { path: "/terms", label: "Terms of service" },
  { path: "/risk-disclosure", label: "Risk disclosure" },
];

export interface LegalSection {
  id: string;
  heading: string;
  /** Paragraphs and lists, in order. A string is a paragraph; an array is a list. */
  body: (string | string[])[];
}

/**
 * The layout the three legal documents share.
 *
 * Sharing one is the correct answer here, not a shortcut: a privacy policy and
 * a terms of service that look like different products invite the suspicion
 * that they say different things about the same subject. What these need is
 * the opposite of the rest of the site — one measured column, generous line
 * height, no motion competing with the sentence you are on, and a table of
 * contents, because nobody reads these linearly. They arrive looking for
 * clause nine.
 *
 * Every heading is an anchor, so support can send someone to the exact
 * paragraph rather than "see our terms".
 */
export function LegalShell({
  title,
  summary,
  updated,
  sections,
}: {
  title: string;
  /** One honest paragraph of what this document does, above the legal text. */
  summary: string;
  /** ISO date, rendered readably and machine-readably. */
  updated: string;
  sections: LegalSection[];
}) {
  const { pathname } = useLocation();
  const [activeId, setActiveId] = useState(sections[0]?.id);

  // Highlight the section being read. A table of contents that never moves is
  // a list of links; one that tracks position is a position indicator.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible) setActiveId(visible.target.id);
      },
      { rootMargin: "-88px 0px -70% 0px" },
    );
    sections.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [sections]);

  const updatedLabel = new Date(updated).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  return (
    <>
      <LegalBackdrop />

      <div className="container-x pt-28 sm:pt-32">
        {/* sibling documents */}
        <nav aria-label="Legal documents" className="flex flex-wrap gap-1.5">
          {LEGAL_PAGES.map((p) => {
            const active = p.path === pathname;
            return (
              <Link
                key={p.path}
                to={p.path}
                onPointerEnter={() => prefetchRoute(p.path)}
                className={cn(
                  "rounded-lg border px-3 py-1.5 text-[12.5px] transition-colors duration-200",
                  active
                    ? "border-gold/40 bg-gold/[0.08] text-gold-soft"
                    : "border-white/[0.08] text-white/45 hover:border-white/20 hover:text-white/80",
                )}
              >
                {p.label}
              </Link>
            );
          })}
        </nav>

        <motion.header
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="mt-8 border-b border-white/[0.08] pb-8"
        >
          <span className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-gold/70">
            <FileText className="h-3.5 w-3.5" />
            Legal
          </span>
          <h1 className="mt-4 text-balance text-3xl font-bold tracking-tight text-white sm:text-[2.75rem]">
            {title}
          </h1>
          <p className="mt-5 max-w-2xl text-[17px] leading-relaxed text-white/60">{summary}</p>
          <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[11px] text-white/30">
            <span>
              Last updated <time dateTime={updated} className="text-white/55">{updatedLabel}</time>
            </span>
            <span className="hidden h-3 w-px bg-white/10 sm:block" />
            <button
              onClick={() => window.print()}
              className="inline-flex items-center gap-1.5 transition-colors hover:text-white/70"
            >
              <Printer className="h-3 w-3" />
              Print or save as PDF
            </button>
          </div>
        </motion.header>

        <div className="grid gap-10 pb-24 pt-10 lg:grid-cols-[minmax(0,1fr)_230px] lg:gap-16">
          {/* the document */}
          <article className="min-w-0 max-w-2xl">
            {sections.map((s, i) => (
              <section key={s.id} id={s.id} className="scroll-mt-24 pt-10 first:pt-0">
                <h2 className="group text-lg font-semibold tracking-tight text-white">
                  <a href={`#${s.id}`} className="no-underline">
                    <span className="mr-2 font-mono text-[13px] text-gold/50">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    {s.heading}
                  </a>
                </h2>
                {s.body.map((block, bi) =>
                  Array.isArray(block) ? (
                    <ul key={bi} className="mt-4 space-y-2">
                      {block.map((item) => (
                        <li key={item} className="flex gap-3 text-[15px] leading-relaxed text-white/60">
                          <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-gold/60" />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p key={bi} className="mt-4 text-[15px] leading-[1.75] text-white/60">
                      {block}
                    </p>
                  ),
                )}
              </section>
            ))}

            <p className="mt-14 rounded-xl border border-white/[0.08] bg-white/[0.02] p-5 text-sm leading-relaxed text-white/45">
              Questions about this document are answered by a person, not a form. Reach us
              through the{" "}
              <Link to="/support" className="text-gold-soft underline-offset-2 hover:underline">
                support center
              </Link>
              . If anything here is unclear, that is worth telling us — an agreement nobody can
              follow is not one worth having.
            </p>
          </article>

          {/* contents */}
          <aside className="order-first lg:order-none lg:sticky lg:top-24 lg:self-start">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/35">
              Contents
            </p>
            <ol className="mt-4 space-y-0.5 border-l border-white/[0.08]">
              {sections.map((s, i) => (
                <li key={s.id}>
                  <a
                    href={`#${s.id}`}
                    className={cn(
                      "-ml-px flex gap-2 border-l py-1.5 pl-3 text-[12.5px] transition-colors duration-200",
                      activeId === s.id
                        ? "border-gold text-white"
                        : "border-transparent text-white/40 hover:border-white/20 hover:text-white/70",
                    )}
                  >
                    <span className="font-mono text-[11px] text-white/25">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    {s.heading}
                  </a>
                </li>
              ))}
            </ol>
          </aside>
        </div>
      </div>
    </>
  );
}
