from __future__ import annotations

BROWSER_RUNTIME_VERSION = "2"
BROWSER_ROOT = ".internet-hands/browser"
BROWSER_RUNTIME_PATH = f"{BROWSER_ROOT}/runtime.mjs"
BROWSER_PACKAGE_PATH = f"{BROWSER_ROOT}/package.json"
BROWSER_READY_PATH = f"{BROWSER_ROOT}/.ready-v{BROWSER_RUNTIME_VERSION}"

BROWSER_PACKAGE_JSON = """{
  \"private\": true,
  \"type\": \"module\",
  \"dependencies\": {
    \"playwright\": \"1.55.0\"
  }
}\n"""

BROWSER_RUNTIME_JS = r'''import fs from "node:fs";
import fsp from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const runtimeDir = path.dirname(fileURLToPath(import.meta.url));
const mode = String(process.argv[2] || "");
const sessionName = String(process.argv[3] || "default");
const requestPath = process.argv[4];
if (!/^[a-z0-9][a-z0-9_-]{0,62}$/.test(sessionName)) {
  throw new Error("invalid browser session name");
}

const sandboxRoot = process.cwd();
const sessionDir = path.join(runtimeDir, "sessions", sessionName);
const profileDir = path.join(sessionDir, "profile");
const statePath = path.join(sessionDir, "state.json");
const consolePath = path.join(sessionDir, "console.jsonl");
const networkPath = path.join(sessionDir, "network.jsonl");
const socketPath = path.join(sessionDir, "control.sock");
const MAX_LOG_BYTES = 4_000_000;
const TRIM_LOG_BYTES = 2_000_000;

function clip(value, max = 2000) {
  const text = String(value ?? "");
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function appendJsonl(file, value) {
  try {
    fs.appendFileSync(file, `${JSON.stringify(value)}\n`, "utf8");
    const stat = fs.statSync(file);
    if (stat.size > MAX_LOG_BYTES) {
      const text = fs.readFileSync(file, "utf8");
      let trimmed = text.slice(-TRIM_LOG_BYTES);
      const newline = trimmed.indexOf("\n");
      if (newline >= 0) trimmed = trimmed.slice(newline + 1);
      fs.writeFileSync(file, trimmed, "utf8");
    }
  } catch {}
}

function isBlockedHost(hostname) {
  const host = String(hostname || "").toLowerCase().replace(/\.$/, "");
  if (!host) return true;
  if (host === "localhost" || host === "metadata.google.internal") return true;
  if (host.endsWith(".localhost")) return true;
  if (host === "169.254.169.254") return true;
  if (/^127\./.test(host) || /^10\./.test(host) || /^192\.168\./.test(host)) return true;
  const m = host.match(/^172\.(\d+)\./);
  if (m && Number(m[1]) >= 16 && Number(m[1]) <= 31) return true;
  if (/^169\.254\./.test(host) || /^0\./.test(host)) return true;
  if (host === "::1" || /^fc/i.test(host) || /^fd/i.test(host) || /^fe8/i.test(host) || /^fe9/i.test(host) || /^fea/i.test(host) || /^feb/i.test(host)) return true;
  return false;
}

function shouldBlockUrl(raw) {
  try {
    const u = new URL(raw);
    if (u.protocol === "http:" || u.protocol === "https:") return isBlockedHost(u.hostname);
    return false;
  } catch {
    return false;
  }
}

function resolveWorkdir(raw) {
  const value = String(raw || "").trim();
  const resolved = value
    ? (path.isAbsolute(value) ? path.normalize(value) : path.resolve(sandboxRoot, value))
    : sandboxRoot;
  if (resolved !== sandboxRoot && !resolved.startsWith(`${sandboxRoot}${path.sep}`)) {
    throw new Error("browser working directory must remain inside the sandbox root");
  }
  return resolved;
}

async function loadState() {
  try {
    return JSON.parse(await fsp.readFile(statePath, "utf8"));
  } catch {
    return {};
  }
}

async function readJsonlTail(file, maxEvents) {
  try {
    const text = await fsp.readFile(file, "utf8");
    const lines = text.split(/\r?\n/).filter(Boolean);
    return lines.slice(-maxEvents).map((line) => {
      try { return JSON.parse(line); } catch { return { raw: clip(line, 2000) }; }
    });
  } catch {
    return [];
  }
}

async function sendRequest(payload) {
  return await new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath);
    let buffer = "";
    const timeoutMs = Math.max(3000, Math.min(Number(payload.timeout_ms || 30000) + 5000, 125000));
    socket.setTimeout(timeoutMs);
    socket.on("connect", () => socket.write(`${JSON.stringify(payload)}\n`));
    socket.on("data", (chunk) => {
      buffer += chunk.toString("utf8");
      const newline = buffer.indexOf("\n");
      if (newline < 0) return;
      const line = buffer.slice(0, newline);
      socket.destroy();
      try { resolve(JSON.parse(line)); } catch (error) { reject(error); }
    });
    socket.on("timeout", () => {
      socket.destroy();
      reject(new Error("browser daemon request timed out"));
    });
    socket.on("error", reject);
  });
}

if (mode === "client") {
  if (!requestPath) throw new Error("request path is required");
  const payload = JSON.parse(await fsp.readFile(requestPath, "utf8"));
  const result = await sendRequest(payload);
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exit(0);
}

if (mode === "ping") {
  const result = await sendRequest({ action: "ping", timeout_ms: 2000 });
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exit(result?.ok ? 0 : 1);
}

if (mode !== "daemon") throw new Error("mode must be daemon, client, or ping");

await fsp.mkdir(profileDir, { recursive: true });
try { await fsp.unlink(socketPath); } catch {}

const { chromium } = await import("playwright");
const context = await chromium.launchPersistentContext(profileDir, {
  headless: true,
  acceptDownloads: true,
  viewport: { width: 1440, height: 900 },
});

await context.route("**/*", async (route) => {
  const url = route.request().url();
  if (shouldBlockUrl(url)) {
    appendJsonl(networkPath, {
      at: new Date().toISOString(),
      type: "blocked",
      method: route.request().method(),
      url: clip(url),
    });
    await route.abort("blockedbyclient");
    return;
  }
  await route.continue();
});

const pages = context.pages();
const page = pages[0] || await context.newPage();

page.on("console", (msg) => {
  appendJsonl(consolePath, {
    at: new Date().toISOString(),
    type: "console",
    level: msg.type(),
    text: clip(msg.text()),
    url: clip(page.url()),
  });
});
page.on("pageerror", (error) => {
  appendJsonl(consolePath, {
    at: new Date().toISOString(),
    type: "pageerror",
    level: "error",
    text: clip(String(error)),
    url: clip(page.url()),
  });
});
page.on("request", (request) => {
  appendJsonl(networkPath, {
    at: new Date().toISOString(),
    type: "request",
    method: request.method(),
    resource_type: request.resourceType(),
    url: clip(request.url()),
  });
});
page.on("response", (response) => {
  appendJsonl(networkPath, {
    at: new Date().toISOString(),
    type: "response",
    status: response.status(),
    url: clip(response.url()),
  });
});

async function saveState() {
  const state = {
    url: clip(page.url(), 4000),
    title: clip(await page.title().catch(() => ""), 1000),
    updated_at: new Date().toISOString(),
  };
  await fsp.writeFile(statePath, JSON.stringify(state, null, 2), "utf8");
  return state;
}

const previous = await loadState();
if (previous.url && page.url() === "about:blank" && !shouldBlockUrl(previous.url)) {
  await page.goto(previous.url, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
}

function locatorFor(selector, nth = 0) {
  if (!selector || typeof selector !== "string") throw new Error("selector is required");
  return page.locator(selector).nth(Number(nth || 0));
}

async function handle(req) {
  const action = String(req.action || "state");
  if (action === "ping") {
    return { ok: true, browser_session: sessionName, state: await saveState() };
  }

  const timeoutMs = Math.min(Math.max(Number(req.timeout_ms || 30000), 100), 120000);
  let result = {};
  if (action === "open") {
    if (!req.url || shouldBlockUrl(req.url)) throw new Error("browser target is blocked");
    const response = await page.goto(req.url, {
      waitUntil: req.wait_until || "domcontentloaded",
      timeout: timeoutMs,
    });
    result = { status: response ? response.status() : null };
  } else if (action === "click") {
    await locatorFor(req.selector, req.nth).click({ timeout: timeoutMs });
    if (req.wait_until) {
      await page.waitForLoadState(req.wait_until, { timeout: timeoutMs }).catch(() => {});
    }
    result = { clicked: true };
  } else if (action === "fill") {
    await locatorFor(req.selector, req.nth).fill(String(req.value ?? ""), { timeout: timeoutMs });
    result = { filled: true };
  } else if (action === "press") {
    await locatorFor(req.selector, req.nth).press(String(req.key || "Enter"), { timeout: timeoutMs });
    result = { pressed: String(req.key || "Enter") };
  } else if (action === "extract") {
    const modeName = String(req.mode || "text");
    const maxChars = Number(req.max_chars || 250000);
    if (modeName === "links") {
      const locator = page.locator(req.selector || "a");
      const total = await locator.count();
      const links = await locator.evaluateAll((nodes) =>
        nodes.slice(0, 200).map((node) => ({
          text: (node.textContent || "").trim().slice(0, 1000),
          href: String(node.href || node.getAttribute("href") || "").slice(0, 2000),
          title: String(node.getAttribute("title") || "").slice(0, 500),
        }))
      );
      result = { mode: modeName, links, truncated: total > 200 };
    } else {
      const locator = page.locator(req.selector || "body").first();
      const value = modeName === "html" ? await locator.innerHTML() : await locator.innerText();
      result = { mode: modeName, content: value.slice(0, maxChars), truncated: value.length > maxChars };
    }
  } else if (action === "screenshot") {
    const output = String(req.output_path || "artifacts/page.png");
    if (path.isAbsolute(output) || output.split(/[\\/]/).includes("..")) {
      throw new Error("output path must be relative and may not contain ..");
    }
    const workdir = resolveWorkdir(req.cwd);
    const target = path.resolve(workdir, output);
    await fsp.mkdir(path.dirname(target), { recursive: true });
    await page.screenshot({ path: target, fullPage: req.full_page !== false });
    result = { path: output, cwd: req.cwd || null, full_page: req.full_page !== false };
  } else if (action === "download") {
    const outputDir = String(req.output_dir || "artifacts/downloads");
    if (path.isAbsolute(outputDir) || outputDir.split(/[\\/]/).includes("..")) {
      throw new Error("output directory must be relative and may not contain ..");
    }
    const workdir = resolveWorkdir(req.cwd);
    const directory = path.resolve(workdir, outputDir);
    await fsp.mkdir(directory, { recursive: true });
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: timeoutMs }),
      locatorFor(req.selector, req.nth).click({ timeout: timeoutMs }),
    ]);
    const suggested = download.suggestedFilename().replace(/[^A-Za-z0-9._-]/g, "_");
    const target = path.join(directory, suggested || "download.bin");
    await download.saveAs(target);
    result = {
      path: path.join(outputDir, suggested || "download.bin"),
      cwd: req.cwd || null,
      suggested_filename: clip(download.suggestedFilename(), 500),
    };
  } else if (action === "trace") {
    const kind = String(req.kind || "console");
    const maxEvents = Math.min(Math.max(Number(req.max_events || 100), 1), 200);
    const file = kind === "network" ? networkPath : consolePath;
    result = { kind, events: await readJsonlTail(file, maxEvents) };
    if (req.clear) await fsp.writeFile(file, "", "utf8");
  } else if (action === "state") {
    result = { live: true };
  } else if (action === "close") {
    result = { closed: true };
  } else {
    throw new Error(`unsupported browser action: ${action}`);
  }

  return { ok: true, browser_session: sessionName, state: await saveState(), ...result };
}

let queue = Promise.resolve();
let shuttingDown = false;
const server = net.createServer((socket) => {
  let buffer = "";
  socket.on("data", (chunk) => {
    buffer += chunk.toString("utf8");
    const newline = buffer.indexOf("\n");
    if (newline < 0) return;
    const line = buffer.slice(0, newline);
    buffer = "";
    let request;
    try {
      request = JSON.parse(line);
    } catch (error) {
      socket.end(`${JSON.stringify({ ok: false, error: clip(error) })}\n`);
      return;
    }
    queue = queue.then(async () => {
      try {
        const response = await handle(request);
        socket.end(`${JSON.stringify(response)}\n`);
        if (request.action === "close" && !shuttingDown) {
          shuttingDown = true;
          setTimeout(async () => {
            try { await context.close(); } catch {}
            server.close();
            try { await fsp.unlink(socketPath); } catch {}
          }, 25);
        }
      } catch (error) {
        socket.end(`${JSON.stringify({ ok: false, error: clip(error, 4000) })}\n`);
      }
    });
  });
});

server.on("error", (error) => {
  process.stderr.write(`${String(error)}\n`);
  process.exitCode = 1;
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    if (shuttingDown) return;
    shuttingDown = true;
    try { await context.close(); } catch {}
    server.close();
    try { await fsp.unlink(socketPath); } catch {}
    process.exit(0);
  });
}

server.listen(socketPath, () => {
  try { fs.chmodSync(socketPath, 0o600); } catch {}
  process.stdout.write(`${JSON.stringify({ ready: true, browser_session: sessionName, socket: socketPath })}\n`);
});
'''
