import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import { Logo } from "@/components/Logo";
import { AuthShowcase } from "./AuthShowcase";
import { DemoModeNotice } from "./DemoModeNotice";

interface AuthShellProps {
  children: ReactNode;
  /** Set false for centered single-card pages (forgot/reset/verify/2FA). */
  split?: boolean;
}

/**
 * Auth page frame. `split` renders the premium two-column layout (showcase left,
 * card right) used by Login/Register; otherwise a centered card used by the
 * minimal flows.
 */
export function AuthShell({ children, split = true }: AuthShellProps) {
  if (!split) {
    return (
      <main className="relative flex min-h-screen flex-col items-center justify-center px-5 py-12">
        <TopBar />
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="w-full max-w-md"
        >
          {children}
        </motion.div>
        <DemoModeNotice className="mt-6" />
      </main>
    );
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-2">
      <AuthShowcase />
      <div className="relative flex flex-col items-center justify-center px-5 py-12 sm:px-10">
        <TopBar />
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="w-full max-w-sm"
        >
          {children}
          <DemoModeNotice className="mt-6" />
        </motion.div>
      </div>
    </main>
  );
}

function TopBar() {
  return (
    <div className="absolute inset-x-0 top-0 flex items-center justify-between px-5 py-5 sm:px-8">
      <Link to="/">
        <Logo compact className="lg:hidden" />
      </Link>
      <Link
        to="/"
        className="ml-auto inline-flex items-center gap-1.5 text-sm text-white/50 transition hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to site
      </Link>
    </div>
  );
}
