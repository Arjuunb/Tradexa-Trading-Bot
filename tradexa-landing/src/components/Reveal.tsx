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
}

/** Consistent centered section header. */
export function SectionHeading({ eyebrow, title, subtitle, className }: SectionHeadingProps) {
  return (
    <Reveal className={className}>
      <div className="mx-auto max-w-2xl text-center">
        <span className="eyebrow">{eyebrow}</span>
        <h2 className="mt-4 text-balance text-3xl font-bold tracking-tight text-white sm:text-4xl">
          {title}
        </h2>
        {subtitle && <p className="mt-4 text-white/55">{subtitle}</p>}
      </div>
    </Reveal>
  );
}
