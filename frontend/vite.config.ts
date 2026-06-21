import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    host: "127.0.0.1",
    port: 5173,
    hmr: {
      host: "127.0.0.1",
      port: 24678
    }
  },
  test: {
    setupFiles: ["./src/test/setup.ts"],
    globals: true
  }
});
