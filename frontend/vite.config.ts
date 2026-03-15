/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    watch: {
      usePolling: true,
    },
    proxy: {
      "/api": {
        target: process.env.API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: process.env.API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
    },
  },
});
