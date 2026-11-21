import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { createConnection, createServer } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const children = [];
let shuttingDown = false;

function log(message) {
  process.stdout.write(`[startup] ${message}\n`);
}

function ensureEnvironmentFile() {
  const envPath = path.join(root, ".env");
  if (existsSync(envPath)) return;
  const examplePath = path.join(root, ".env.example");
  if (!existsSync(examplePath)) {
    throw new Error("Missing .env.example; cannot initialize local configuration.");
  }
  const secret = randomBytes(48).toString("base64url");
  const example = readFileSync(examplePath, "utf8");
  const contents = example.replace(
    /^JWT_SECRET_KEY=.*$/m,
    `JWT_SECRET_KEY=${secret}`,
  );
  writeFileSync(envPath, contents, { flag: "wx" });
  log("Created private .env with a generated JWT key.");
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    shell: process.platform === "win32",
    ...options,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} failed with exit code ${result.status ?? "unknown"}.`);
  }
}

function ensureDependencies() {
  const python = path.join(root, "venv", "Scripts", "python.exe");
  if (!existsSync(python)) {
    log("Creating the backend virtual environment and installing requirements...");
    run("py", ["-3", "-m", "venv", "venv"]);
  }
  const pythonExecutable = existsSync(python) ? python : path.join(root, "venv", "bin", "python");
  const backendPackages = spawnSync(pythonExecutable, ["-m", "pip", "show", "fastapi", "uvicorn", "pymongo"], {
    cwd: root,
    stdio: "ignore",
  });
  if (backendPackages.status !== 0) {
    log("Installing backend requirements...");
    run(pythonExecutable, ["-m", "pip", "install", "-r", "requirements.txt"]);
  }
  if (!existsSync(path.join(root, "frontend", "node_modules", "vite"))) {
    log("Installing frontend requirements...");
    run(process.platform === "win32" ? "npm.cmd" : "npm", ["install", "--prefix", "frontend"]);
  }
}

function readEnvValue(name, fallback) {
  const environment = readFileSync(path.join(root, ".env"), "utf8");
  const line = environment.split(/\r?\n/).find((entry) => entry.trimStart().startsWith(`${name}=`));
  if (!line) return fallback;
  const value = line.slice(line.indexOf("=") + 1).trim();
  return value.replace(/^["']|["']$/g, "") || fallback;
}

function startProcess(label, command, args, options = {}) {
  const { critical = true, ...spawnOptions } = options;
  const child = spawn(command, args, {
    cwd: root,
    env: process.env,
    stdio: ["inherit", "pipe", "pipe"],
    windowsHide: true,
    ...spawnOptions,
  });
  children.push(child);
  for (const [stream, output] of [["stdout", process.stdout], ["stderr", process.stderr]]) {
    let pending = "";
    child[stream].on("data", (chunk) => {
      pending += chunk.toString();
      const lines = pending.split(/\r?\n/);
      pending = lines.pop() ?? "";
      for (const line of lines) output.write(`[${label}] ${line}\n`);
    });
    child[stream].on("end", () => {
      if (pending) output.write(`[${label}] ${pending}\n`);
    });
  }
  child.on("error", (error) => log(`${label} could not start: ${error.message}`));
  child.on("exit", (code, signal) => {
    if (critical && !shuttingDown && code !== 0) {
      log(`${label} exited unexpectedly (${signal ?? `exit ${code}`}); stopping the other development services.`);
      void shutdown();
    }
  });
  return child;
}

async function isPortListening(port, host = "127.0.0.1") {
  return new Promise((resolve) => {
    const socket = createServer();
    socket.once("error", () => resolve(true));
    socket.once("listening", () => socket.close(() => resolve(false)));
    socket.listen(port, host);
  });
}

async function isTcpReachable(host, port, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const socket = createConnection({ host, port });
    const finish = (reachable) => {
      socket.destroy();
      resolve(reachable);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

async function getJson(url, timeoutMs = 1500) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

async function waitFor(check, durationMs, intervalMs = 1000) {
  const deadline = Date.now() + durationMs;
  while (Date.now() < deadline) {
    if (await check()) return true;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

function findOllama() {
  const pathEntries = (process.env.PATH ?? "").split(path.delimiter);
  const candidates = [
    ...pathEntries.map((entry) => path.join(entry, "ollama.exe")),
    path.join(process.env.LOCALAPPDATA ?? "", "Programs", "Ollama", "ollama.exe"),
    "C:\\Program Files\\Ollama\\ollama.exe",
  ];
  return candidates.find((candidate) => candidate && existsSync(candidate));
}

async function startOllama(executable) {
  const baseUrl = readEnvValue("OLLAMA_BASE_URL", "http://localhost:11434").replace(/\/+$/, "");
  const tagUrl = `${baseUrl}/api/tags`;
  if (!(await getJson(tagUrl))) {
    startProcess("ollama", executable, ["serve"], { critical: false });
    const reachable = await waitFor(async () => Boolean(await getJson(tagUrl)), 25000);
    if (!reachable) {
      log("Ollama did not become reachable within 25 seconds; the API and frontend will still start.");
      return;
    }
    log("Started the local Ollama server.");
  } else {
    log("Using the already-running local Ollama server.");
  }

  const model = readEnvValue("OLLAMA_MODEL", "llama3.2:3b");
  const tags = await getJson(tagUrl);
  const installed = (tags?.models ?? []).some((entry) => entry?.name === model || entry?.name === `${model}:latest`);
  if (!installed) {
    log(`Downloading configured Ollama model ${model}; first download may take several minutes.`);
    startProcess("ollama-pull", executable, ["pull", model], { critical: false });
  } else {
    log(`Configured Ollama model ${model} is already installed.`);
  }
}

async function ensureOllama() {
  const executable = findOllama();
  if (executable) {
    await startOllama(executable);
    return;
  }
  if (process.platform !== "win32" || !process.env.LOCALAPPDATA) {
    log("Ollama is not installed; English AI answers will remain unavailable until Ollama is installed.");
    return;
  }

  const wingetActive = spawnSync(
    "powershell.exe",
    ["-NoProfile", "-Command", "if (Get-Process winget -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"],
    { cwd: root, stdio: "ignore" },
  ).status === 0;
  if (wingetActive) {
    log("Ollama installation is already running; checking for its runtime in the background.");
    const ready = await waitFor(() => Boolean(findOllama()), 90000, 2000);
    if (!ready) {
      log("Ollama is still installing. English AI will become available after installation and model download finish.");
      return;
    }
    const installedExecutable = findOllama();
    if (installedExecutable) await startOllama(installedExecutable);
    return;
  }

  log("Ollama is missing; starting its Windows installation in the background.");
  const installer = startProcess("ollama-install", "winget.exe", [
    "install", "--id", "Ollama.Ollama", "--exact", "--silent",
    "--accept-package-agreements", "--accept-source-agreements",
  ], { critical: false });
  installer.once("exit", (code) => {
    const installedExecutable = findOllama();
    if (code === 0 && installedExecutable) {
      log("Ollama runtime installed.");
      void startOllama(installedExecutable).catch((error) => log(`Ollama startup failed: ${error.message}`));
    } else {
      log("Ollama installation did not complete; install it manually to enable AI answers.");
    }
  });
}

async function ensureMongoDB() {
  const uri = readEnvValue("MONGODB_URI", "mongodb://localhost:27017/");
  if (uri.startsWith("mongodb+srv://")) {
    log("MongoDB SRV URI configured; the API health endpoint will check database connectivity.");
    return;
  }
  const match = uri.match(/^mongodb(?:\+srv)?:\/\/(?:[^@/]+@)?([^/:?]+)/);
  const host = match?.[1] ?? "localhost";
  if (await isTcpReachable(host === "localhost" ? "127.0.0.1" : host, 27017)) {
    log("MongoDB is listening.");
    return;
  }
  if (/^(localhost|127\.0\.0\.1)$/i.test(host) && process.platform === "win32") {
    const startService = spawnSync("powershell.exe", [
      "-NoProfile",
      "-Command",
      "Start-Service -Name MongoDB -ErrorAction Stop",
    ], { cwd: root, stdio: "ignore" });
    if (startService.status === 0 && await waitFor(() => isTcpReachable("127.0.0.1", 27017), 15000)) {
      log("Started the MongoDB Windows service.");
      return;
    }
  }
  log(`MongoDB is not reachable at ${host}:27017. The API will start, but database-backed features need MongoDB.`);
}

async function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) child.kill();
  }
  await Promise.all(children.map((child) => new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) return resolve();
    child.once("exit", resolve);
    setTimeout(resolve, 4000).unref();
  })));
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

try {
  ensureEnvironmentFile();
  ensureDependencies();
  await ensureMongoDB();

  const apiUrl = "http://127.0.0.1:5000/api/health";
  if (!(await getJson(apiUrl))) {
    if (await isPortListening(5000)) {
      throw new Error("Port 5000 is occupied by an API without the expected health route; stop that process and retry.");
    }
    const python = path.join(root, "venv", "Scripts", "python.exe");
    startProcess("api", python, [
      "-m", "uvicorn", "backend.app.main:app",
      "--reload", "--reload-dir", "backend",
      "--host", "127.0.0.1", "--port", "5000",
    ]);
  } else {
    log("The API is already running at http://127.0.0.1:5000.");
  }

  if (await isPortListening(5173)) {
    log("Port 5173 is already serving a frontend; reusing it.");
  } else {
    startProcess(
      "web",
      process.execPath,
      [path.join(root, "frontend", "node_modules", "vite", "bin", "vite.js"), "--host", "127.0.0.1", "--strictPort"],
      { cwd: path.join(root, "frontend") },
    );
  }

  void ensureOllama().catch((error) => log(`Ollama startup failed: ${error.message}`));
  const apiReady = await waitFor(async () => Boolean(await getJson(apiUrl)), 25000);
  if (apiReady) {
    log("Backend API ready at http://127.0.0.1:5000; MongoDB health checked.");
  } else {
    log("Backend startup is pending or failed; check the [api] log above.");
  }
  log("Frontend URL: http://127.0.0.1:5173 (press Ctrl+C to stop launched development servers).");
  await new Promise(() => {});
} catch (error) {
  log(error instanceof Error ? error.message : String(error));
  await shutdown();
}
