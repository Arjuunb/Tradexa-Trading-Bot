import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Standalone premium landing + auth app for the Tradexa Trading Bot.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    rollupOptions: {
      output: {
        // Split the dependencies that never change from the app code that
        // changes every deploy. Previously one 473KB chunk carried both, so
        // every release re-downloaded React and framer-motion alongside a
        // one-line copy edit. These also fetch in parallel with the app chunk
        // rather than behind it.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          motion: ["framer-motion"],
        },
      },
    },
  },
  server: { port: 5175 },
});
