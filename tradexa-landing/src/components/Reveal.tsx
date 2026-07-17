import { motion } from "framer-motion";
import type { ReactNode } from "react";

interface RevealProps {
  children: ReactNode;
  delay?: number;
  className?: string;
  y?: number;
}

/** Scroll-triggered fade-up. Reusable across every landing section. */
export function Reveal({ children, delay = 0, className, y = 24 }: RevealProps) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.6, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

interface SectionHeadingProps {
  eyebrow: string;
  title: ReactNode;
  subtitle?: string;
  className?: string;
  /** Anchor for this section (e.g. "#engine"). When set, the heading becomes a
   *  clickable deep link: clicking it sets the URL hash and smooth-scrolls the
   *  section into place, and a gold "#" affordance appears on hover. */
  link?: string;
}

/** Consistent centered section header. */
export function SectionHeading({ eyebrow, title, subtitle, className, link }: SectionHeadingProps) {
  const heading = (
    <h2 className="mt-4 text-balance text-3xl font-bold tracking-tight text-white sm:text-4xl">
      {title}
    </h2>
  );
  return (
    <Reveal className={className}>
      <div className="mx-auto max-w-2xl text-center">
        {link ? (
          <a href={link} className="group inline-block no-underline" aria-label={`Link to this section`}>
            <span className="eyebrow transition-colors group-hover:text-gold">{eyebrow}</span>
            <span className="relative block">
              {heading}
              <span
                aria-hidden
                className="absolute -right-6 top-1/2 hidden -translate-y-1/4 text-2xl font-bold text-gold/0 transition-colors group-hover:text-gold/60 sm:inline"
              >
                #
              </span>
            </span>
          </a>
        ) : (
          <>
            <span className="eyebrow">{eyebrow}</span>
            {heading}
          </>
        )}
        {subtitle && <p className="mt-4 text-white/55">{subtitle}</p>}
      </div>
    </Reveal>
  );
}
