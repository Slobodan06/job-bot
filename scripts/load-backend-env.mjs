import fs from "node:fs";
import path from "node:path";

/** Merge backend/.env into env without overriding existing process.env keys. */
export function loadBackendEnv(env, backendDir) {
  const envPath = path.join(backendDir, ".env");
  if (!fs.existsSync(envPath)) return env;
  const text = fs.readFileSync(envPath, "utf8");
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"'))
      || (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!(key in env)) env[key] = value;
  }
  return env;
}
