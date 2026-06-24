import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
const backend = path.join(root, "backend");
const dist = path.resolve(root, "frontend", "dist");

if (!fs.existsSync(path.join(dist, "index.html"))) {
  console.error("Missing frontend/dist/index.html. Run: npm run build");
  process.exit(1);
}

const venvPython =
  process.platform === "win32"
    ? path.join(backend, ".venv", "Scripts", "python.exe")
    : path.join(backend, ".venv", "bin", "python");

const python = fs.existsSync(venvPython) ? venvPython : process.platform === "win32" ? "py" : "python3";
const port = process.env.PORT || "8080";

console.log(`
  Open in your browser (not 0.0.0.0 — module scripts often fail to load there):
    http://127.0.0.1:${port}/
    http://localhost:${port}/
  Listening on 0.0.0.0:${port} for LAN/Docker only.
`);

const child = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", String(port)],
  {
    cwd: backend,
    stdio: "inherit",
    env: { ...process.env, FRONTEND_DIST: dist },
  },
);

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
