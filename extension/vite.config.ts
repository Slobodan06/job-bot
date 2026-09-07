import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { crx } from "@crxjs/vite-plugin";

import manifest from "./manifest.config";

export default defineConfig({
  plugins: [react(), crx({ manifest })],
  define: {
    __JOBBOT_API_ORIGIN__: JSON.stringify(
      process.env.JOBBOT_API_ORIGIN || "http://localhost:8000",
    ),
    __JOBBOT_WEB_ORIGIN__: JSON.stringify(
      process.env.JOBBOT_WEB_ORIGIN || "http://localhost:5173",
    ),
  },
  build: { outDir: "dist", emptyOutDir: true, target: "esnext" },
});
