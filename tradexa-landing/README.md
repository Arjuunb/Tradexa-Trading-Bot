# Tradexa Trading Bot — Landing + Authentication

A premium, dark-luxury marketing site and complete authentication experience for
the Tradexa Trading Bot. Design language: **Bloomberg Terminal precision ×
Apple restraint × Linear polish** — institutional-grade, minimal, fast.

> Tagline: **Automated Trading. Human Intelligence.**

## Stack

- **React 18 + TypeScript + Vite** (fast build, code-split routes)
- **TailwindCSS** with a bespoke dark-luxury token set (black `#08080A`, gold
  `#C8A94B`, emerald, soft red)
- **Framer Motion** — page transitions, scroll reveals, count-ups, toasts
- **React Hook Form + Zod** — typed forms with live inline validation
- **Supabase** — authentication (email/password, Google, GitHub, TOTP 2FA)
- **Lucide** icons · shadcn-style UI primitives (hand-owned in `components/ui`)

## What's inside

**Landing** (`/`): Navbar · Hero with an animated dashboard preview · Features ·
How it works · Product screenshots · Performance metrics · Security · Footer.

**Auth** (`/auth/*`): `login`, `register`, `forgot-password`, `reset-password`,
`verify-email`, `two-factor`, `session-expired`.

## Getting started

```bash
npm install
cp .env.example .env      # optional — add Supabase keys to go live
npm run dev               # http://localhost:5175
npm run build             # type-check + production build
npm run preview
```

### Authentication — demo vs live

The auth layer runs in **demo mode** until Supabase credentials are present:
forms fully validate, animate and give honest feedback, but no real account is
created (a banner says so). Provide the two public env vars to go live — **no
code changes required**:

```env
VITE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key      # safe to expose in the browser
VITE_APP_URL=/app                         # where "Launch Bot" / post-login goes
```

The `anon` key is designed to be public; keep the `service_role` key server-side
only. Enable the Google and GitHub providers (and, optionally, TOTP MFA) in the
Supabase dashboard to activate those buttons.

## Design & integrity notes

- **No fabricated metrics.** The dashboard/screenshot visuals are clearly
  labelled **preview · demo data** and never presented as a live account or a
  real track record. The performance figures are stated as engineering targets,
  not return guarantees.
- **Accessible & responsive:** keyboard-navigable, focus-visible rings, reduced-
  motion support, semantic labels, mobile-first layouts.
- **Fast:** auth pages are lazy-loaded; the landing ships the minimal bundle.

## Deploy

Static SPA — deploy `dist/` anywhere. `vercel.json` includes the SPA rewrite so
deep links to `/auth/*` resolve to `index.html`. Point `VITE_APP_URL` at the
running Automation Hub dashboard so **Launch Bot** and post-login land there.
