import { motion } from "framer-motion";
import { Fingerprint, KeyRound, Network, ScrollText, ServerCog, ShieldCheck, type LucideIcon } from "lucide-react";
import { SecurityBackdrop } from "@/components/site/backdrops";
import {
  AuditLog,
  DeploymentMap,
  EnvelopeDiagram,
  PermissionMatrix,
  ZeroTrustDiagram,
} from "@/components/site/security/diagrams";
import { useRouteMeta } from "@/site/seo";
import { routeFor } from "@/site/routes";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * /security — zero-trust by construction.
 *
 * Navy under emerald: cool, procedural, and deliberately the least decorated
 * page on the site. Every section leads with the mechanism and only then says
 * what it buys you, which is the reverse of how security pages usually read
 * and the only order under which the claims are checkable.
 *
 * Structured as a numbered dossier rather than a marketing stack — the reader
 * here is often looking for one specific answer, and numbered sections are
 * navigable in a way that a scroll of feature cards is not.
 */

interface Chapter {
  n: string;
  id: string;
  icon: LucideIcon;
  title: string;
  lead: string;
}

const CHAPTERS: Chapter[] = [
  {
    n: "01",
    id: "keys",
    icon: KeyRound,
    title: "Where your keys live",
    lead: "A trading key is the only thing you hand over, so it is worth being exact about what happens to it.",
  },
  {
    n: "02",
    id: "scope",
    icon: Fingerprint,
    title: "What the key is allowed to do",
    lead: "Encryption protects a secret at rest. Scope protects you from what the secret can do if it ever leaks.",
  },
  {
    n: "03",
    id: "zero-trust",
    icon: Network,
    title: "Zero trust, meaning no implicit trust",
    lead: "Being inside the network is not a credential. Every hop authenticates independently.",
  },
  {
    n: "04",
    id: "audit",
    icon: ScrollText,
    title: "A record nobody can quietly edit",
    lead: "An audit log that can be amended is a formality. This one chains.",
  },
  {
    n: "05",
    id: "deployment",
    icon: ServerCog,
    title: "Where it runs",
    lead: "Regional isolation, per-tenant separation, and no shared execution state between accounts.",
  },
];

function ChapterHead({ chapter }: { chapter: Chapter }) {
  const Icon = chapter.icon;
  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.55, ease: EASE }}
      className="flex gap-5"
    >
      <div className="hidden shrink-0 sm:block">
        <span className="flex h-12 w-12 items-center justify-center rounded-xl border border-emerald/30 bg-emerald/[0.07] text-emerald-soft">
          <Icon className="h-5 w-5" />
        </span>
        <span className="mt-2 block text-center font-mono text-[10px] text-white/20">{chapter.n}</span>
      </div>
      <div>
        <h2 className="text-balance text-2xl font-bold tracking-tight text-white sm:text-3xl">
          {chapter.title}
        </h2>
        <p className="mt-3 max-w-2xl leading-relaxed text-white/55">{chapter.lead}</p>
      </div>
    </motion.div>
  );
}

export default function SecurityPage() {
  const route = routeFor("/security")!;
  useRouteMeta(route);


  return (
    <>
      <SecurityBackdrop />

      {/* ── Hero: claim on the left, mechanism on the right ─────────────── */}
      <section className="container-x pt-32 sm:pt-40">
        <div className="grid gap-12 lg:grid-cols-[1fr_0.95fr] lg:items-center">
          <div className="min-w-0">
            <motion.span
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: EASE }}
              className="inline-flex items-center gap-2 rounded-full border border-emerald/30 bg-emerald/[0.07] px-3 py-1"
            >
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-soft" />
              <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-emerald-soft">
                Security
              </span>
            </motion.span>

            <motion.h1
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.06, ease: EASE }}
              className="mt-6 text-balance text-4xl font-extrabold leading-[1.05] tracking-tight text-white sm:text-5xl lg:text-[3.6rem]"
            >
              Your keys cannot
              <br />
              <span className="bg-emerald-sheen bg-clip-text text-transparent">move your money.</span>
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.14, ease: EASE }}
              className="mt-6 max-w-xl text-[17px] leading-relaxed text-white/55"
            >
              That is a structural statement, not a policy one. A key with withdrawal permission
              is refused at connection time, secrets are decrypted only inside a service with no
              public route, and every administrative action lands in a log that cannot be edited
              from inside the product.
            </motion.p>

            <motion.dl
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.2, ease: EASE }}
              className="mt-10 grid max-w-lg grid-cols-2 gap-4 border-t border-emerald/15 pt-6 sm:grid-cols-4"
            >
              {[
                ["AES-256", "envelope"],
                ["TLS 1.3", "in transit"],
                ["0", "withdrawal scopes"],
                ["Append", "only audit"],
              ].map(([v, k]) => (
                <div key={k} className="min-w-0">
                  <dt className="font-mono text-base font-semibold text-emerald-soft">{v}</dt>
                  <dd className="mt-1 text-[11px] uppercase tracking-[0.12em] text-white/30">{k}</dd>
                </div>
              ))}
            </motion.dl>
          </div>

          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.8, delay: 0.16, ease: EASE }}
          >
            <EnvelopeDiagram />
          </motion.div>
        </div>

        {/* chapter index — this page is consulted, not read */}
        <motion.nav
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3, ease: EASE }}
          aria-label="Sections"
          className="mt-16 grid gap-2 sm:grid-cols-3 lg:grid-cols-5"
        >
          {CHAPTERS.map((c) => (
            <a
              key={c.id}
              href={`#${c.id}`}
              className="group rounded-xl border border-navy-500/70 bg-navy-800/50 p-3 transition-colors hover:border-emerald/40 hover:bg-navy-700/50"
            >
              <span className="font-mono text-[10px] text-white/25">{c.n}</span>
              <span className="mt-1 block text-[13px] text-white/70 transition-colors group-hover:text-white">
                {c.title}
              </span>
            </a>
          ))}
        </motion.nav>
      </section>

      {/* ── 01 · Keys ───────────────────────────────────────────────────── */}
      <section id="keys" className="container-x mt-24 scroll-mt-24 sm:mt-32">
        <ChapterHead chapter={CHAPTERS[0]} />
        <div className="mt-8 grid gap-4 lg:grid-cols-2">
          {[
            ["Entered once", "The secret is submitted directly to the key service over TLS and encrypted before the response returns. It is never held by the web app, never placed in a session, and never rendered again."],
            ["Decrypted in one place", "Only the execution service can unwrap a data key, and only in memory for the duration of a request. It has no inbound public route and no interactive shell."],
            ["Rotatable without downtime", "A replacement key can be attached and the old one revoked while positions are open; in-flight orders continue under the outgoing key until it drains."],
            ["Never in a log", "Secrets are redacted at the serialiser rather than at each call site, so a new endpoint cannot leak one by omission."],
          ].map(([t, b], i) => (
            <motion.div
              key={t}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.45, delay: i * 0.06, ease: EASE }}
              className="rounded-2xl border border-navy-500/60 bg-navy-800/50 p-5"
            >
              <h3 className="text-[15px] font-semibold text-white">{t}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/50">{b}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── 02 · Scope ──────────────────────────────────────────────────── */}
      <section id="scope" className="container-x mt-24 scroll-mt-24 sm:mt-32">
        <ChapterHead chapter={CHAPTERS[1]} />
        <div className="mt-8 grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-start">
          <PermissionMatrix />
          <div className="space-y-4">
            {[
              ["IP allowlisting", "Where a venue supports it, the connection is bound to our egress addresses, so a leaked key is unusable from anywhere else."],
              ["Separate keys per venue", "One key per venue per tenant. Revoking one never interrupts another."],
              ["Read-only mode", "A connection can be attached in read-only scope to run analysis and paper trading against a real account without any order permission at all."],
            ].map(([t, b], i) => (
              <motion.div
                key={t}
                initial={{ opacity: 0, x: 12 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.45, delay: i * 0.07, ease: EASE }}
                className="rounded-2xl border border-navy-500/60 bg-navy-800/50 p-5"
              >
                <h3 className="text-[15px] font-semibold text-white">{t}</h3>
                <p className="mt-2 text-sm leading-relaxed text-white/50">{b}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 03 · Zero trust ─────────────────────────────────────────────── */}
      <section id="zero-trust" className="container-x mt-24 scroll-mt-24 sm:mt-32">
        <ChapterHead chapter={CHAPTERS[2]} />
        <div className="mt-8">
          <ZeroTrustDiagram />
        </div>
      </section>

      {/* ── 04 · Audit ──────────────────────────────────────────────────── */}
      <section id="audit" className="container-x mt-24 scroll-mt-24 sm:mt-32">
        <ChapterHead chapter={CHAPTERS[3]} />
        <div className="mt-8">
          <AuditLog />
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {[
            ["What is recorded", "Configuration changes, key attach and rotate, strategy promotion, halts, resumes, manual overrides and every order lifecycle event."],
            ["What is stored with it", "Actor, source address, user agent, the previous value and the new one — enough to answer “who changed this” without a second system."],
            ["Where it can go", "Exportable on a schedule to your own retention or SIEM, so the record survives independently of us."],
          ].map(([t, b], i) => (
            <motion.div
              key={t}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.4, delay: i * 0.06 }}
              className="rounded-xl border border-navy-500/60 bg-navy-800/40 p-4"
            >
              <h3 className="font-mono text-[10px] uppercase tracking-[0.14em] text-emerald-soft">{t}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/50">{b}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── 05 · Deployment ─────────────────────────────────────────────── */}
      <section id="deployment" className="container-x mt-24 scroll-mt-24 pb-24 sm:mt-32">
        <ChapterHead chapter={CHAPTERS[4]} />
        <div className="mt-8">
          <DeploymentMap />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-2xl border border-navy-500/60 bg-navy-800/50 p-6">
            <h3 className="text-[15px] font-semibold text-white">Tenant isolation</h3>
            <ul className="mt-3 space-y-2.5">
              {[
                "Per-tenant data keys — decrypting one account's secrets tells you nothing about another's",
                "Row-level authorisation enforced in the data layer, not in the request handler",
                "Execution workers are pinned per tenant; no shared order state between accounts",
                "Backups are encrypted with the same envelope scheme and restored per tenant",
              ].map((l) => (
                <li key={l} className="flex gap-2.5 text-sm text-white/55">
                  <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-emerald" />
                  <span>{l}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-2xl border border-navy-500/60 bg-navy-800/50 p-6">
            <h3 className="text-[15px] font-semibold text-white">Operational posture</h3>
            <ul className="mt-3 space-y-2.5">
              {[
                "Immutable deploys — no in-place patching, every release is a new image",
                "Secrets injected at runtime from a managed store; none exist in the repository or the image",
                "Least-privilege workload identities with short-lived credentials, rotated automatically",
                "Risk and execution fail closed: if a dependency is unreachable, trading stops rather than continues unchecked",
              ].map((l) => (
                <li key={l} className="flex gap-2.5 text-sm text-white/55">
                  <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-emerald" />
                  <span>{l}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <motion.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className={cn(
            "mt-6 rounded-2xl border border-navy-500/60 bg-navy-800/40 p-5 text-sm leading-relaxed text-white/45",
          )}
        >
          Security is a claim you should be able to check. If something here is not specific
          enough to verify, that is a defect in the page — tell us and we will make it concrete or
          remove it.
        </motion.p>
      </section>
    </>
  );
}
