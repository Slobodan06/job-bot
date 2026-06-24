import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
const backend = path.join(root, "backend");
const venvPython =
  process.platform === "win32"
    ? path.join(backend, ".venv", "Scripts", "python.exe")
    : path.join(backend, ".venv", "bin", "python");

const python = fs.existsSync(venvPython) ? venvPython : process.platform === "win32" ? "py" : "python3";

const env = { ...process.env };
delete env.FRONTEND_DIST;
// Default 8010: Windows often forbids 8000 (WinError 10013) when it sits in an excluded port range.
const apiPort = env.API_PORT || "8010";

const child = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", apiPort],
  {
    cwd: backend,
    stdio: "inherit",
    env,
  },
);

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
