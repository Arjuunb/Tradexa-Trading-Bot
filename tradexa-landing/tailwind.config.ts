import type { Config } from "tailwindcss";

/**
 * Tradexa Trading Bot — dark-luxury design tokens.
 * Bloomberg Terminal precision × Apple restraint × Linear polish.
 */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Core surfaces
        ink: {
          DEFAULT: "#08080A", // primary black
          800: "#0C0C0F",
          700: "#111114",
          600: "#17171B",
          500: "#1E1E23",
          400: "#2A2A31",
        },
        // Brand
        gold: {
          DEFAULT: "#C9A24B",
          soft: "#E7CE86",
          deep: "#8A7233",
        },
        // Secondary brand accent — TradeLogX Nexus "signal blue" (data / links)
        signal: {
          DEFAULT: "#3E7BD6",
          soft: "#6EA3EC",
          deep: "#13233F",
        },
        emerald: {
          DEFAULT: "#2FBF71",
          soft: "#4FD98E",
          deep: "#1E9457",
        },
        loss: {
          DEFAULT: "#E5605B", // soft red
          soft: "#F07E7A",
          deep: "#C24A45",
        },
        line: "rgba(255,255,255,0.08)",
        "line-strong": "rgba(255,255,255,0.14)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        xl: "1rem",
        "2xl": "1.25rem",
        "3xl": "1.75rem",
      },
      boxShadow: {
        glass: "0 1px 0 0 rgba(255,255,255,0.05) inset, 0 24px 60px -20px rgba(0,0,0,0.7)",
        gold: "0 10px 40px -12px rgba(200,169,75,0.45)",
        card: "0 20px 50px -24px rgba(0,0,0,0.8)",
      },
      backgroundImage: {
        "gold-sheen": "linear-gradient(135deg, #E7D89A 0%, #C8A94B 45%, #A98E3A 100%)",
        "radial-fade": "radial-gradient(ellipse 80% 60% at 50% -10%, rgba(200,169,75,0.14), transparent 60%)",
        // page base: barely-warm charcoal falling to true black — depth without
        // leaving the near-black identity
        "page-depth":
          "radial-gradient(120% 85% at 50% 0%, #0D0C0A 0%, #08080A 48%, #050506 100%)",
        "grid-lines":
          "linear-gradient(to right, rgba(226,214,182,0.045) 1px, transparent 1px), linear-gradient(to bottom, rgba(226,214,182,0.045) 1px, transparent 1px)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        float: {
          "0%,100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        bloom: {
          "0%,100%": { transform: "translate(-50%, 0) scale(1)", opacity: "1" },
          "50%": { transform: "translate(-46%, 2rem) scale(1.08)", opacity: "0.85" },
        },
        "bloom-slow": {
          "0%,100%": { transform: "translate(0, 0) scale(1)" },
          "50%": { transform: "translate(-3rem, -2.5rem) scale(1.12)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgba(47,191,113,0.45)" },
          "70%": { boxShadow: "0 0 0 8px rgba(47,191,113,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(47,191,113,0)" },
        },
        "grid-pan": {
          "0%": { backgroundPosition: "0 0" },
          "100%": { backgroundPosition: "40px 40px" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.6s cubic-bezier(0.22,1,0.36,1) both",
        float: "float 6s ease-in-out infinite",
        shimmer: "shimmer 2.5s infinite",
        "pulse-ring": "pulse-ring 2s cubic-bezier(0.4,0,0.6,1) infinite",
        "grid-pan": "grid-pan 8s linear infinite",
        bloom: "bloom 18s ease-in-out infinite",
        "bloom-slow": "bloom-slow 26s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
