import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// DASHBOARD_BASE lets the single-origin Docker image serve the dashboard under a
// sub-path (e.g. "/app/") while the landing site owns "/". Defaults to "/" so
// the standalone Vercel deploy and the e2e tests are unchanged.
const base = process.env.DASHBOARD_BASE || "/";

export default defineConfig({
  base,
  plugins: [react()],
  server: { port: 5173 },
});
