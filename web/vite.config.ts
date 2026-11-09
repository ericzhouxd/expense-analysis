import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API runs separately (`uv run expense-app --no-browser`); the dev server proxies to it.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8765" },
    fs: { allow: [".."] },
  },
  build: { outDir: "dist", emptyOutDir: true, assetsInlineLimit: 0 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
