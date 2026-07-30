import { motion, useReducedMotion } from "framer-motion";
import { Children, type ReactNode } from "react";
import { Link } from "react-router-dom";

// One easing curve for the whole site. A gentle overshoot-free ease-out: motion
// decelerates into place rather than stopping dead, which is what makes a
// reveal read as settling instead of snapping.
const EASE = [0.22, 1, 0.36, 1] as const;
const DURATION = 0.55;
// Reveal a little BEFORE the element reaches the viewport edge, so the motion
// finishes as it becomes comfortably readable rather than starting there.
const VIEWPORT = { once: true, margin: "-80px" } as const;

interface RevealProps {
  children: ReactNode;
  delay?: number;
  className?: string;
  y?: number;
}

/** Scroll-triggered fade-up. Reusable across every landing section. */
export function Reveal({ children, delay = 0, className, y = 24 }: RevealProps) {
  // MotionConfig at the app root already handles this globally; honouring it
  // here too keeps the travel distance at 0 rather than merely un-animated,
  // so no layout shift is baked into the initial state.
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: reduced ? 0 : y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={VIEWPORT}
      transition={{ duration: DURATION, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

interface RevealGroupProps {
  children: ReactNode;
  className?: string;
  /** Seconds between each child. Kept small — past ~0.1s a grid of cards
   *  stops reading as one group arriving and starts feeling like a queue. */
  stagger?: number;
  delay?: number;
  y?: number;
}

/**
 * Reveals children in sequence rather than all at once.
 *
 * A grid of six feature cards fading in on the same frame reads as a single
 * flat block; the same six offset by 60ms each read as related items settling
 * into place, and the eye is led left-to-right instead of having to pick an
 * entry point. The stagger is orchestrated by the parent's variants so the
 * children need no per-item delay arithmetic.
 */
export function RevealGroup({ children, className, stagger = 0.06, delay = 0,
                              y = 20 }: RevealGroupProps) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial="hidden"
      whileInView="shown"
      viewport={VIEWPORT}
      variants={{
        hidden: {},
        // Staggering is motion, so collapse it under the reduced-motion
        // preference too — otherwise the page still ripples, just without
        // the travel.
        shown: { transition: { staggerChildren: reduced ? 0 : stagger, delayChildren: delay } },
      }}
    >
      {Children.map(children, (child, i) => (
        <motion.div
          key={i}
          variants={{
            hidden: { opacity: 0, y: reduced ? 0 : y },
            shown: { opacity: 1, y: 0, transition: { duration: DURATION, ease: EASE } },
          }}
        >
          {child}
        </motion.div>
      ))}
    </motion.div>
  );
}

interface SectionHeadingProps {
  eyebrow: string;
  title: ReactNode;
  subtitle?: string;
  className?: string;
  /**
   * Where this section's heading leads.
   *
   * A "#anchor" makes the heading a deep link to itself, with a gold "#" on
   * hover. A route path ("/engine") instead sends the reader to that
   * section's dedicated page, and the affordance becomes an arrow — because
   * the two do genuinely different things and a single glyph for both would
   * be a lie about one of them.
   */
  link?: string;
}

/** Consistent centered section header. */
export function SectionHeading({ eyebrow, title, subtitle, className, link }: SectionHeadingProps) {
  const isRoute = !!link && link.startsWith("/");
  const heading = (
    <h2 className="mt-4 text-balance text-3xl font-bold tracking-tight text-white sm:text-4xl">
      {title}
    </h2>
  );
  const inner = (
    <>
      <span className="eyebrow transition-colors group-hover:text-gold">{eyebrow}</span>
      <span className="relative block">
        {heading}
        <span
          aria-hidden
          className="absolute -right-7 top-1/2 hidden -translate-y-1/4 text-2xl font-bold text-gold/0 transition-all duration-300 group-hover:text-gold/60 sm:inline"
        >
          {isRoute ? "→" : "#"}
        </span>
      </span>
    </>
  );

  return (
    <Reveal className={className}>
      <div className="mx-auto max-w-2xl text-center">
        {link ? (
          isRoute ? (
            <Link to={link} className="group inline-block no-underline" aria-label={`Read more about ${eyebrow}`}>
              {inner}
            </Link>
          ) : (
            <a href={link} className="group inline-block no-underline" aria-label="Link to this section">
              {inner}
            </a>
          )
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
