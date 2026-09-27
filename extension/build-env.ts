/**
 * Which JobBot server the extension is built against.
 *
 * Resolution (highest priority first):
 *   1. Real environment variables:  JOBBOT_API_ORIGIN=https://… npm run build
 *   2. .env.[mode].local  (personal overrides, git-ignored)
 *   3. .env.[mode]        (.env.production for `npm run build`,
 *                          .env.development for `npm run dev` / `npm run build:local`)
 *
 * The URL is compiled into the extension, so after changing it rebuild and
 * reload the extension in chrome://extensions.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadEnv } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));

function toOrigin(name: string, value: string): string {
  try {
    return new URL(value.trim()).origin; // drops trailing slashes/paths
  } catch {
    throw new Error(`${name} must be a full URL like https://your-app.up.railway.app (got "${value}")`);
  }
}

export function resolveOrigins(mode: string): { apiOrigin: string; webOrigin: string } {
  const env = loadEnv(mode, here, "JOBBOT_");
  if (!env.JOBBOT_API_ORIGIN) {
    throw new Error(`JOBBOT_API_ORIGIN is not set — add it to extension/.env.${mode} or the environment.`);
  }
  const apiOrigin = toOrigin("JOBBOT_API_ORIGIN", env.JOBBOT_API_ORIGIN);
  // The API serves the web app too, so they share an origin unless told otherwise.
  const webOrigin = env.JOBBOT_WEB_ORIGIN ? toOrigin("JOBBOT_WEB_ORIGIN", env.JOBBOT_WEB_ORIGIN) : apiOrigin;
  return { apiOrigin, webOrigin };
}
