from __future__ import annotations

BROWSER_RUNTIME_VERSION = "1"
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
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const runtimeDir = path.dirname(fileURLToPath(import.meta.url));
const requestPath = process.argv[2];
if (!requestPath) throw new Error("request path is required");
const req = JSON.parse(await fsp.readFile(requestPath, "utf8"));
const sessionName = String(req.browser_session || "default");
if (!/^[a-z0-9][a-z0-9_-]{0,62}$/.test(sessionName)) {
  throw new Error("invalid browser session name");
}

const sessionDir = path.join(runtimeDir, "sessions", sessionName);
const profileDir = path.join(sessionDir, "profile");
const statePath = path.join(sessionDir, "state.json");
const consolePath = path.join(sessionDir, "console.jsonl");
const networkPath = path.join(sessionDir, "network.jsonl");
await fsp.mkdir(profileDir, { recursive: true });

function clip(value, max = 2000) {
  const text = String(value ?? "");
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function appendJsonl(file, value) {
  try {
    fs.appendFileSync(file, `${JSON.stringify(value)}\n`, "utf8");
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

async function loadState() {
  try {
    return JSON.parse(await fsp.readFile(statePath, "utf8"));
  } catch {
    return {};
  }
}

async function saveState(page) {
  const state = {
    url: clip(page.url(), 4000),
    title: clip(await page.title().catch(() => ""), 1000),
    updated_at: new Date().toISOString(),
  };
  await fsp.writeFile(statePath, JSON.stringify(state, null, 2), "utf8");
  return state;
}

function locatorFor(page, selector, nth = 0) {
  if (!selector || typeof selector !== "string") throw new Error("selector is required");
  return page.locator(selector).nth(Number(nth || 0));
}

async function readJsonlTail(file, maxEvents) {
  try {
    const text = await fsp.readFile(file, "utf8");
    const lines = text.split(/\r?\n/).filter(Boolean);
    return lines.slice(-maxEvents).map((line) => {
      try { return JSON.parse(line); } catch { return { raw: clip(line, 4000) }; }
    });
  } catch {
    return [];
  }
}

const context = await chromium.launchPersistentContext(profileDir, {
  headless: true,
  acceptDownloads: true,
  viewport: {
    width: Number(req.viewport_width || 1440),
    height: Number(req.viewport_height || 900),
  },
});

await context.route("**/*", async (route) => {
  const url = route.request().url();
  if (shouldBlockUrl(url)) {
    appendJsonl(networkPath, {
      at: new Date().toISOString(),
      type: "blocked",
      method: route.request().method(),
      url: clip(url, 4000),
    });
    await route.abort("blockedbyclient");
    return;
  }
  await route.continue();
});

let pages = context.pages();
let page = pages[0] || await context.newPage();

page.on("console", (msg) => {
  appendJsonl(consolePath, {
    at: new Date().toISOString(),
    type: "console",
    level: msg.type(),
    text: clip(msg.text(), 4000),
    url: clip(page.url(), 4000),
  });
});
page.on("pageerror", (error) => {
  appendJsonl(consolePath, {
    at: new Date().toISOString(),
    type: "pageerror",
    level: "error",
    text: clip(String(error), 4000),
    url: clip(page.url(), 4000),
  });
});
page.on("request", (request) => {
  appendJsonl(networkPath, {
    at: new Date().toISOString(),
    type: "request",
    method: request.method(),
    resource_type: request.resourceType(),
    url: clip(request.url(), 4000),
  });
});
page.on("response", (response) => {
  appendJsonl(networkPath, {
    at: new Date().toISOString(),
    type: "response",
    status: response.status(),
    url: clip(response.url(), 4000),
  });
});

const previous = await loadState();
const action = String(req.action || "state");
if (action !== "open" && previous.url && page.url() === "about:blank") {
  if (!shouldBlockUrl(previous.url)) {
    await page.goto(previous.url, {
      waitUntil: "domcontentloaded",
      timeout: Number(req.timeout_ms || 30000),
    }).catch(() => {});
  }
}

let result = {};
try {
  if (action === "open") {
    if (!req.url || shouldBlockUrl(req.url)) throw new Error("browser target is blocked");
    const response = await page.goto(req.url, {
      waitUntil: req.wait_until || "domcontentloaded",
      timeout: Number(req.timeout_ms || 30000),
    });
    result = { status: response ? response.status() : null };
  } else if (action === "click") {
    await locatorFor(page, req.selector, req.nth).click({
      timeout: Number(req.timeout_ms || 30000),
    });
    if (req.wait_until) {
      await page.waitForLoadState(req.wait_until, {
        timeout: Number(req.timeout_ms || 30000),
      }).catch(() => {});
    }
    result = { clicked: true };
  } else if (action === "fill") {
    await locatorFor(page, req.selector, req.nth).fill(String(req.value ?? ""), {
      timeout: Number(req.timeout_ms || 30000),
    });
    result = { filled: true };
  } else if (action === "press") {
    await locatorFor(page, req.selector, req.nth).press(String(req.key || "Enter"), {
      timeout: Number(req.timeout_ms || 30000),
    });
    result = { pressed: String(req.key || "Enter") };
  } else if (action === "extract") {
    const mode = String(req.mode || "text");
    const maxChars = Number(req.max_chars || 250000);
    if (mode === "links") {
      const locator = page.locator(req.selector || "a");
      const total = await locator.count();
      const links = await locator.evaluateAll((nodes) =>
        nodes.slice(0, 500).map((node) => ({
          text: (node.textContent || "").trim().slice(0, 1000),
          href: String(node.href || node.getAttribute("href") || "").slice(0, 4000),
          title: String(node.getAttribute("title") || "").slice(0, 1000),
        }))
      );
      result = { mode, links, truncated: total > 500 };
    } else {
      const locator = page.locator(req.selector || "body").first();
      const value = mode === "html" ? await locator.innerHTML() : await locator.innerText();
      result = {
        mode,
        content: value.slice(0, maxChars),
        truncated: value.length > maxChars,
      };
    }
  } else if (action === "screenshot") {
    const output = String(req.output_path || "artifacts/page.png");
    if (path.isAbsolute(output) || output.split(/[\\/]/).includes("..")) {
      throw new Error("output path must be relative and may not contain ..");
    }
    await fsp.mkdir(path.dirname(path.resolve(process.cwd(), output)), { recursive: true });
    await page.screenshot({
      path: output,
      fullPage: req.full_page !== false,
    });
    result = { path: output, full_page: req.full_page !== false };
  } else if (action === "download") {
    const outputDir = String(req.output_dir || "artifacts/downloads");
    if (path.isAbsolute(outputDir) || outputDir.split(/[\\/]/).includes("..")) {
      throw new Error("output directory must be relative and may not contain ..");
    }
    await fsp.mkdir(path.resolve(process.cwd(), outputDir), { recursive: true });
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: Number(req.timeout_ms || 30000) }),
      locatorFor(page, req.selector, req.nth).click({ timeout: Number(req.timeout_ms || 30000) }),
    ]);
    const suggested = download.suggestedFilename().replace(/[^A-Za-z0-9._-]/g, "_");
    const target = path.join(outputDir, suggested || "download.bin");
    await download.saveAs(target);
    result = { path: target, suggested_filename: clip(download.suggestedFilename(), 1000) };
  } else if (action === "trace") {
    const kind = String(req.kind || "console");
    const maxEvents = Math.min(Math.max(Number(req.max_events || 200), 1), 1000);
    const file = kind === "network" ? networkPath : consolePath;
    result = { kind, events: await readJsonlTail(file, maxEvents) };
    if (req.clear) await fsp.writeFile(file, "", "utf8");
  } else if (action === "state") {
    result = { previous };
  } else {
    throw new Error(`unsupported browser action: ${action}`);
  }

  const state = await saveState(page);
  process.stdout.write(`${JSON.stringify({ ok: true, browser_session: sessionName, state, ...result })}\n`);
} finally {
  await context.close();
}
'''
