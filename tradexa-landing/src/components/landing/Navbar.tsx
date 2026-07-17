import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Menu, X } from "lucide-react";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/Button";
import { cn, APP_URL } from "@/lib/utils";

const LINKS = [
  { label: "Features", href: "#features" },
  { label: "Engine", href: "#engine" },
  { label: "Live trade", href: "#trade-in-action" },
  { label: "Selectivity", href: "#selectivity" },
  { label: "How it works", href: "#how" },
  { label: "Security", href: "#security" },
];

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <motion.header
      initial={{ y: -24, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      className={cn(
        "fixed inset-x-0 top-0 z-50 transition-all duration-300",
        scrolled ? "border-b border-line bg-ink/70 backdrop-blur-xl" : "border-b border-transparent",
      )}
    >
      <nav className="container-x flex h-16 items-center justify-between">
        <Link to="/" aria-label="TradeLogX Nexus home">
          <Logo />
        </Link>

        <div className="hidden items-center gap-8 md:flex">
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="text-sm text-white/60 transition-colors hover:text-white"
            >
              {l.label}
            </a>
          ))}
        </div>

        <div className="hidden items-center gap-2 md:flex">
          <Link to="/auth/login">
            <Button variant="ghost" size="sm">
              Sign in
            </Button>
          </Link>
          <a href={APP_URL}>
            <Button size="sm">Launch Bot</Button>
          </a>
        </div>

        <button
          className="text-white/80 md:hidden"
          onClick={() => setOpen((o) => !o)}
          aria-label="Toggle menu"
        >
          {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </nav>

      {open && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="border-t border-line bg-ink/95 px-5 py-4 md:hidden"
        >
          <div className="flex flex-col gap-1">
            {LINKS.map((l) => (
              <a
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                className="rounded-lg px-3 py-2.5 text-sm text-white/70 hover:bg-white/5"
              >
                {l.label}
              </a>
            ))}
            <div className="mt-2 flex gap-2">
              <Link to="/auth/login" className="flex-1">
                <Button variant="secondary" fullWidth size="sm">
                  Sign in
                </Button>
              </Link>
              <a href={APP_URL} className="flex-1">
                <Button fullWidth size="sm">
                  Launch Bot
                </Button>
              </a>
            </div>
          </div>
        </motion.div>
      )}
    </motion.header>
  );
}
