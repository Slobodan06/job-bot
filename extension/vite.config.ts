import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { crx } from "@crxjs/vite-plugin";

import { resolveOrigins } from "./build-env";
import buildManifest from "./manifest.config";

// `vite build` (mode "production") targets the deployed server from .env.production;
// `vite` / `vite build --mode development` target a local server from .env.development.
export default defineConfig(({ mode }) => {
  const { apiOrigin, webOrigin } = resolveOrigins(mode);
  return {
    plugins: [react(), crx({ manifest: buildManifest(apiOrigin) })],
    define: {
      __JOBBOT_API_ORIGIN__: JSON.stringify(apiOrigin),
      __JOBBOT_WEB_ORIGIN__: JSON.stringify(webOrigin),
    },
    build: { outDir: "dist", emptyOutDir: true, target: "esnext" },
  };
});
