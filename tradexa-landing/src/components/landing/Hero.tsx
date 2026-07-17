import { motion } from "framer-motion";
import { ArrowRight, BookOpen, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { DashboardPreview } from "./DashboardPreview";
import { APP_URL } from "@/lib/utils";

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] } },
};

export function Hero() {
  return (
    <section className="relative pt-32 sm:pt-40">
      <div className="container-x grid items-center gap-16 lg:grid-cols-[1.05fr_1fr]">
        {/* left copy */}
        <motion.div variants={container} initial="hidden" animate="show">
          <motion.div variants={item}>
            <span className="eyebrow">
              <ShieldCheck className="h-3.5 w-3.5" />
              AI Trading Intelligence System
            </span>
          </motion.div>

          <motion.h1
            variants={item}
            className="mt-6 text-balance text-5xl font-extrabold leading-[1.03] tracking-tight text-white sm:text-6xl lg:text-[4.25rem]"
          >
            AI-Powered Trading
            <br />
            <span className="text-gold-gradient">Intelligence System</span>
          </motion.h1>

          <motion.p variants={item} className="mt-6 max-w-xl text-lg leading-relaxed text-white/60">
            Analyze markets, test strategies, and automate intelligent trading decisions through a
            powerful AI-driven platform built for modern traders.
          </motion.p>

          <motion.div variants={item} className="mt-9 flex flex-col gap-3 sm:flex-row">
            <a href={APP_URL}>
              <Button size="lg" className="group">
                Launch Platform
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Button>
            </a>
            <a href="#docs">
              <Button size="lg" variant="secondary">
                <BookOpen className="h-4 w-4" />
                View Documentation
              </Button>
            </a>
          </motion.div>

          <motion.div
            variants={item}
            className="mt-10 flex items-center gap-6 text-xs text-white/40"
          >
            <span className="tabular">Platform</span>
            <span className="h-4 w-px bg-line" />
            <span className="font-medium text-white/60">Intelligent infrastructure for modern traders.</span>
          </motion.div>
        </motion.div>

        {/* right preview */}
        <DashboardPreview />
      </div>
    </section>
  );
}
