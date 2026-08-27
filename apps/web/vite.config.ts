/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Local `npm run dev` proxies /api the same way nginx does in Docker, so
    // the browser always talks to one origin and VITE_API_BASE_URL can stay
    // unset in both environments.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/healthz": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
