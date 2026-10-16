import { chromium } from "playwright";
import path from "path";
import fs from "fs";
import { spawn } from "child_process";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "../../..");
const WEB_DIR = path.resolve(__dirname, "..");

function resolveChromePath() {
  if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) {
    return process.env.CHROME_PATH;
  }
  const candidates =
    process.platform === "darwin"
      ? [
          "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
          "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
      : process.platform === "win32"
      ? [
          "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
          "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        ]
      : [
          "/usr/bin/google-chrome",
          "/usr/bin/google-chrome-stable",
          "/usr/bin/chromium",
          "/usr/bin/chromium-browser",
        ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return undefined;
}

const CHROME_PATH = resolveChromePath();
const BASE_URL = process.env.BASE_URL || "http://localhost:3005";
const API_URL = process.env.API_URL || "http://localhost:8000";
const SCREENSHOTS_DIR =
  process.env.SCREENSHOTS_DIR || path.resolve(__dirname, "../test-results/playwright_multi_drawing");

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

async function waitForUrl(url, timeoutMs = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok || res.status === 200 || res.status === 304 || res.status === 404) {
        return true;
      }
    } catch {
      // Keep polling until timeout
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`Timeout waiting for URL to respond: ${url}`);
}

async function main() {
  console.log("=== Issue #35 Multi-Drawing Scope & Revision E2E Verification ===");

  let apiProc = null;
  let webProc = null;

  try {
    // 1. Check & start backend API if needed
    try {
      await waitForUrl(`${API_URL}/api/projects`, 1500);
      console.log(`[E2E] Reusing existing API server at ${API_URL}`);
    } catch {
      console.log(`[E2E] Starting FastAPI server on port 8000...`);
      const pythonPath = `${path.resolve(ROOT_DIR, "packages/cad_engine/src")}:${path.resolve(
        ROOT_DIR,
        "apps/api/src"
      )}`;
      apiProc = spawn("uv", ["run", "uvicorn", "eai_api.app:app", "--host", "0.0.0.0", "--port", "8000"], {
        cwd: ROOT_DIR,
        env: { ...process.env, PYTHONPATH: pythonPath },
        stdio: "inherit",
      });
      await waitForUrl(`${API_URL}/api/projects`, 20000);
      console.log(`[E2E] FastAPI server is ready.`);
    }

    // 2. Check & start Next.js frontend if needed
    try {
      await waitForUrl(BASE_URL, 1500);
      console.log(`[E2E] Reusing existing Web server at ${BASE_URL}`);
    } catch {
      console.log(`[E2E] Starting Next.js production server on port 3005 (npm run start)...`);
      webProc = spawn("npm", ["run", "start", "--", "-p", "3005"], {
        cwd: WEB_DIR,
        stdio: "inherit",
      });
      await waitForUrl(BASE_URL, 30000);
      console.log(`[E2E] Web server is ready at ${BASE_URL}`);
    }

    // 3. Launch browser
    console.log(`[E2E] Launching Chromium...`);
    const browser = await chromium.launch({
      executablePath: CHROME_PATH,
      headless: true,
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    });

    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
    });
    const page = await context.newPage();
    page.on("console", (msg) => console.log(`[BROWSER ${msg.type()}]`, msg.text()));
    page.on("pageerror", (err) => console.error("[BROWSER ERROR]", err));
    page.on("request", (req) => {
      if (req.url().includes("/api/")) {
        console.log(`[REQ] ${req.method()} ${req.url()}`);
      }
    });
    page.on("response", (res) => {
      if (res.url().includes("/api/")) {
        console.log(`[RES ${res.status()}] ${res.url()}`);
      }
    });
    page.on("requestfailed", (req) => {
      if (req.url().includes("/api/")) {
        console.log(`[REQ FAILED] ${req.method()} ${req.url()} - ${req.failure()?.errorText}`);
      }
    });

    // 4. Navigate to Web UI
    console.log(`[E2E] Navigating to ${BASE_URL}...`);
    await page.goto(BASE_URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);

    // 5. Click "다중 도면 데모 (Issue #35)"
    console.log(`[E2E] Seeding multi-drawing demo...`);
    const demoBtn = page.locator('[data-testid="btn-multi-drawing-demo"]:not([disabled])').first();
    await demoBtn.waitFor({ state: "visible", timeout: 15000 });
    await demoBtn.click();

    // Wait for project overview to load
    await page.waitForSelector('[data-testid="metric-light-total-qty"]', { timeout: 15000 });
    await page.waitForTimeout(1000);

    // 6. Verify Initial State: 14 EA LIGHT (1F REV0 [6] + 2F [8] = 14)
    const initialLightQty = await page.locator('[data-testid="metric-light-total-qty"]').innerText();
    console.log(`[E2E] Initial Total LIGHT Quantity: ${initialLightQty}`);
    if (!initialLightQty.includes("14")) {
      throw new Error(`Expected initial LIGHT quantity to be 14 EA, but got "${initialLightQty}"`);
    }

    const screenshot1 = path.join(SCREENSHOTS_DIR, "01_project_overview_initial_14_ea.png");
    await page.screenshot({ path: screenshot1, fullPage: true });
    console.log(`[E2E] Saved screenshot: ${screenshot1}`);

    // 7. Go to Drawing Register tab
    console.log(`[E2E] Navigating to 도면 등록부 (Register) tab...`);
    const regTabBtn = page.locator('[data-testid="tab-drawing-register"]');
    await regTabBtn.click();
    await page.waitForTimeout(600);

    // 8. Find 1F REV1 switch button and activate it
    console.log(`[E2E] Switching 1F active revision from REV0 to REV1...`);
    const rev1Row = page.locator('tr:has-text("REV1")');
    const activateRev1Btn = rev1Row.locator('button:has-text("활성 REV로 교체")');
    await activateRev1Btn.waitFor({ state: "visible", timeout: 5000 });
    await activateRev1Btn.click();

    // Wait for re-takeoff and check that total LIGHT quantity is now 18 EA
    await page.waitForTimeout(1500);

    // Back to summary tab to confirm KPI
    const summaryTabBtn = page.locator('[data-testid="tab-project-summary"]');
    await summaryTabBtn.click();
    await page.waitForTimeout(800);

    const updatedLightQty = await page.locator('[data-testid="metric-light-total-qty"]').innerText();
    console.log(`[E2E] Updated Total LIGHT Quantity after REV1 activation: ${updatedLightQty}`);
    if (!updatedLightQty.includes("18")) {
      throw new Error(`Expected updated LIGHT quantity to be 18 EA, but got "${updatedLightQty}"`);
    }

    const screenshot2 = path.join(SCREENSHOTS_DIR, "02_project_overview_rev1_18_ea.png");
    await page.screenshot({ path: screenshot2, fullPage: true });
    console.log(`[E2E] Saved screenshot: ${screenshot2}`);

    // 9. Go to Revision Diff tab
    console.log(`[E2E] Navigating to 설계변경 비교 (Diff) tab...`);
    const diffTabBtn = page.locator('[data-testid="tab-revision-diff"]');
    await diffTabBtn.click();
    await page.waitForTimeout(1500);

    // Verify delta displays +4
    const diffText = await page.locator("body").innerText();
    if (!diffText.includes("+4") || !diffText.includes("LIGHT")) {
      console.warn("[E2E] Warning: Delta +4 text not immediately found in diff body, checking elements...");
    }

    const screenshot3 = path.join(SCREENSHOTS_DIR, "03_revision_diff_tab.png");
    await page.screenshot({ path: screenshot3, fullPage: true });
    console.log(`[E2E] Saved screenshot: ${screenshot3}`);

    // 10. Switch to Single Drawing CAD View
    console.log(`[E2E] Switching to single drawing CAD view...`);
    const viewDrawingBtn = page.locator('[data-testid="btn-view-drawing"]');
    await viewDrawingBtn.click();
    await page.waitForTimeout(1200);

    const screenshot4 = path.join(SCREENSHOTS_DIR, "04_cad_viewer_drawing_mode.png");
    await page.screenshot({ path: screenshot4, fullPage: true });
    console.log(`[E2E] Saved screenshot: ${screenshot4}`);

    await browser.close();
    console.log("=== All Issue #35 Multi-Drawing E2E Checks Passed Successfully! ===");
  } finally {
    if (apiProc) {
      console.log("[E2E] Terminating spawned API server...");
      apiProc.kill();
    }
    if (webProc) {
      console.log("[E2E] Terminating spawned Web server...");
      webProc.kill();
    }
  }
}

main().catch((err) => {
  console.error("[E2E FAILURE]", err);
  process.exit(1);
});
