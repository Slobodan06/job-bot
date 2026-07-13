import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadBackendEnv } from "./load-backend-env.mjs";
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

function portInUse(checkPort) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.once("error", () => resolve(true));
    probe.once("listening", () => {
      probe.close(() => resolve(false));
    });
    probe.listen(checkPort, "0.0.0.0");
  });
}

if (await portInUse(Number(port))) {
  console.error(`
  Port ${port} is already in use — a server is probably already running.

  Open:  http://127.0.0.1:${port}/builder

  To restart, stop the old process first:
    netstat -ano | findstr ":${port}"
    Stop-Process -Id <PID> -Force

  Then run: npm start
`);
  process.exit(1);
}

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
    env: loadBackendEnv({ ...process.env, FRONTEND_DIST: dist }, backend),
  },
);
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
