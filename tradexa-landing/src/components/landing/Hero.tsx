import { useRef } from "react";
import {
  motion,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
} from "framer-motion";
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
  const reduced = useReducedMotion() ?? false;
  const ref = useRef<HTMLElement | null>(null);

  // scroll-driven depth: as the hero scrolls away, layers travel at different
  // rates so the scene reads as parallax rather than a flat page.
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const copyY = useTransform(scrollYProgress, [0, 1], [0, -64]);
  const copyOpacity = useTransform(scrollYProgress, [0, 0.85], [1, 0]);
  const previewY = useTransform(scrollYProgress, [0, 1], [0, -128]);
  const ambientY = useTransform(scrollYProgress, [0, 1], [0, 90]);
  const cueOpacity = useTransform(scrollYProgress, [0, 0.15], [1, 0]);

  // pointer-driven 3D tilt on the preview (subtle, spring-smoothed).
  const px = useMotionValue(0); // -0.5 .. 0.5
  const py = useMotionValue(0);
  const rotX = useSpring(useTransform(py, [-0.5, 0.5], [6, -6]), { stiffness: 120, damping: 18 });
  const rotY = useSpring(useTransform(px, [-0.5, 0.5], [-7, 7]), { stiffness: 120, damping: 18 });

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (reduced) return;
    const r = e.currentTarget.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width - 0.5);
    py.set((e.clientY - r.top) / r.height - 0.5);
  };
  const onLeave = () => { px.set(0); py.set(0); };

  return (
    <section ref={ref} className="relative pt-32 sm:pt-40">
      {/* hero-local ambient bloom — parallaxes independently of the page backdrop */}
      {!reduced && (
        <motion.div aria-hidden style={{ y: ambientY }} className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
          <div className="absolute -top-24 right-1/4 h-[26rem] w-[34rem] rounded-full bg-gold/[0.06] blur-[120px]" />
          <div className="absolute top-1/3 left-[-6rem] h-[22rem] w-[28rem] rounded-full bg-emerald-deep/[0.05] blur-[130px]" />
        </motion.div>
      )}

      <div className="container-x grid items-center gap-16 lg:grid-cols-[1.05fr_1fr]">
        {/* left copy */}
        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          style={reduced ? undefined : { y: copyY, opacity: copyOpacity }}
        >
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

        {/* right preview — parallax depth + pointer tilt */}
        <motion.div
          style={reduced ? undefined : { y: previewY, perspective: 1200 }}
          onMouseMove={onMove}
          onMouseLeave={onLeave}
        >
          {reduced ? (
            <DashboardPreview />
          ) : (
            <motion.div style={{ rotateX: rotX, rotateY: rotY, transformStyle: "preserve-3d" }}>
              <DashboardPreview />
            </motion.div>
          )}
        </motion.div>
      </div>

      {/* scroll cue */}
      {!reduced && (
        <motion.div
          style={{ opacity: cueOpacity }}
          className="pointer-events-none mx-auto mt-16 hidden w-fit flex-col items-center gap-2 sm:flex"
          aria-hidden
        >
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/30">Scroll</span>
          <span className="flex h-8 w-5 items-start justify-center rounded-full border border-line p-1">
            <motion.span
              className="h-1.5 w-1 rounded-full bg-gold"
              animate={{ y: [0, 8, 0], opacity: [1, 0.3, 1] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
            />
          </span>
        </motion.div>
      )}
    </section>
  );
}
