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
const BASE_URL = process.env.BASE_URL || "http://localhost:3008";
const API_URL = process.env.API_URL || "http://localhost:8008";
const SCREENSHOTS_DIR =
  process.env.SCREENSHOTS_DIR || path.resolve(__dirname, "../test-results/playwright_route_measurement");
const DOCS_SCREENSHOTS_DIR = path.resolve(ROOT_DIR, "docs/screenshots");

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}
if (!fs.existsSync(DOCS_SCREENSHOTS_DIR)) {
  fs.mkdirSync(DOCS_SCREENSHOTS_DIR, { recursive: true });
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
      // Keep polling
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`Timeout waiting for URL to respond: ${url}`);
}

async function main() {
  console.log("=== Issue #37 Scale Calibration & Route Measurement E2E Smoke Verification ===");

  let apiProc = null;
  let webProc = null;

  try {
    // 1. Check & start backend API if needed
    try {
      await waitForUrl(`${API_URL}/api/projects`, 1500);
      console.log(`[E2E] Reusing existing API server at ${API_URL}`);
    } catch {
      console.log(`[E2E] Starting FastAPI server on port 8008...`);
      const pythonPath = `${path.resolve(ROOT_DIR, "packages/cad_engine/src")}:${path.resolve(
        ROOT_DIR,
        "apps/api/src"
      )}`;
      apiProc = spawn("uv", ["run", "uvicorn", "eai_api.app:app", "--host", "0.0.0.0", "--port", "8008"], {
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
      console.log(`[E2E] Starting Next.js production server on port 3008 (npm run start)...`);
      webProc = spawn("npm", ["run", "start", "--", "-p", "3008"], {
        cwd: WEB_DIR,
        env: { ...process.env, NEXT_PUBLIC_API_URL: API_URL },
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

    // 4. Navigate to Web UI
    console.log(`[E2E] Navigating to ${BASE_URL}...`);
    await page.goto(BASE_URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);

    // 5. Seed Route Oracle Demo using toolbar button
    console.log(`[E2E] Clicking "2D 경로 데모 (7m)" toolbar button...`);
    const oracleBtn = page.locator('[data-testid="btn-route-oracle-demo"]:not([disabled])');
    await oracleBtn.waitFor({ state: "visible", timeout: 15000 });
    await oracleBtn.click();
    await page.waitForTimeout(2000);

    // 6. Switch to Project Overview to verify isolated KPIs
    console.log(`[E2E] Switching to Project Overview...`);
    const viewProjBtn = page.locator('[data-testid="btn-view-project"]');
    await viewProjBtn.waitFor({ state: "visible", timeout: 10000 });
    await viewProjBtn.click();
    await page.waitForTimeout(1500);

    // Verify Project Overview KPI cards
    await page.waitForSelector('[data-testid="metric-route-total-length-m"]', { timeout: 15000 });
    const routeTotalLengthText = await page.locator('[data-testid="metric-route-total-length-m"]').innerText();
    console.log(`[E2E] Route Total Length KPI: ${routeTotalLengthText}`);
    if (!routeTotalLengthText.includes("7.0")) {
      throw new Error(`Expected route total length KPI to include "7.0", got "${routeTotalLengthText}"`);
    }

    const equipTotalText = await page.locator('[data-testid="metric-equipment-total-ea"]').innerText();
    console.log(`[E2E] Equipment Total KPI: ${equipTotalText}`);
    if (equipTotalText.trim() !== "0") {
      throw new Error(`Expected equipment total KPI to be "0" (isolated from m), got "${equipTotalText}"`);
    }

    const shot1 = path.join(SCREENSHOTS_DIR, "01_route_oracle_project_kpi.png");
    await page.screenshot({ path: shot1, fullPage: true });
    console.log(`[E2E] Saved screenshot: ${shot1}`);

    // 7. Open single drawing CAD view
    console.log(`[E2E] Switching to CAD Viewer...`);
    const viewDwgBtn = page.locator('[data-testid="btn-view-drawing"]');
    await viewDwgBtn.click();
    await page.waitForTimeout(1500);

    // Verify drawing canvas is visible
    await page.waitForSelector("svg", { timeout: 10000 });

    // 8. Check Calibration and Routes overlay
    const shot2 = path.join(SCREENSHOTS_DIR, "02_cad_viewer_route_overlay.png");
    await page.screenshot({ path: shot2, fullPage: true });
    console.log(`[E2E] Saved screenshot: ${shot2}`);

    // 9. Check the Routes tab on the right panel
    console.log(`[E2E] Checking Routes Tab...`);
    const routesTabBtn = page.locator('[data-testid="tab-routes"]');
    await routesTabBtn.waitFor({ state: "visible", timeout: 5000 });
    await routesTabBtn.click();
    await page.waitForTimeout(800);

    const routesTabText = await page.locator('[data-testid="routes-list-tab"]').innerText();
    console.log(`[E2E] Routes tab content:\n${routesTabText}`);
    if (!routesTabText.includes("7.00 m") || !routesTabText.includes("2.5sq")) {
      throw new Error(`Expected routes list to display "7.00 m" and "2.5sq", got:\n${routesTabText}`);
    }

    // Click on the route item to show selected route card
    const routeItem = page.locator('[data-testid^="route-item-"]').first();
    await routeItem.click();
    await page.waitForTimeout(600);

    await page.waitForSelector('[data-testid="selected-route-card"]', { timeout: 5000 });
    const selCardText = await page.locator('[data-testid="selected-route-card"]').innerText();
    console.log(`[E2E] Selected route card text:\n${selCardText}`);
    if (!selCardText.includes("7.00 m")) {
      throw new Error(`Selected route card does not display 7.00 m!`);
    }

    // 10. Check Takeoff Table Tab for provisional m item
    console.log(`[E2E] Checking Takeoff Table Tab...`);
    const takeoffTabBtn = page.locator('[data-testid="tab-takeoff"]');
    await takeoffTabBtn.click();
    await page.waitForTimeout(800);

    const takeoffBadgeText = await page.locator('[data-testid="takeoff-summary-badges"]').innerText();
    console.log(`[E2E] Takeoff Summary Badges: ${takeoffBadgeText}`);
    if (!takeoffBadgeText.includes("7.0 m") && !takeoffBadgeText.includes("7.00 m")) {
      throw new Error(`Expected takeoff summary badges to include "7.0 m", got "${takeoffBadgeText}"`);
    }

    const shot3 = path.join(SCREENSHOTS_DIR, "03_routes_tab_and_takeoff.png");
    await page.screenshot({ path: shot3, fullPage: true });
    console.log(`[E2E] Saved screenshot: ${shot3}`);

    // Also copy shot2 to docs/screenshots/issue-37-route-measurement.png
    const docShot = path.join(DOCS_SCREENSHOTS_DIR, "issue-37-route-measurement.png");
    fs.copyFileSync(shot2, docShot);
    console.log(`[E2E] Saved primary documentation screenshot: ${docShot}`);

    // 11. Interactive 2D route drawing
    console.log(`[E2E] Testing Interactive 2D Route Drawing...`);
    const routeModeBtn = page.locator('[data-testid="btn-route-measure-mode"]');
    await routeModeBtn.click();
    await page.waitForTimeout(500);

    // Click on SVG canvas to draw a route
    const svgCanvas = page.locator("svg").first();
    const box = await svgCanvas.boundingBox();
    if (box) {
      const startX = box.x + box.width * 0.4;
      const startY = box.y + box.height * 0.4;
      await page.mouse.click(startX, startY);
      await page.waitForTimeout(200);
      await page.mouse.click(startX + 60, startY);
      await page.waitForTimeout(200);
      await page.mouse.click(startX + 60, startY + 80);
      await page.waitForTimeout(300);

      // Finish route by pressing Enter
      await page.keyboard.press("Enter");
      await page.waitForTimeout(1500);

      const shot4 = path.join(SCREENSHOTS_DIR, "04_interactive_route_added.png");
      await page.screenshot({ path: shot4, fullPage: true });
      console.log(`[E2E] Saved interactive route screenshot: ${shot4}`);
    }

    await browser.close();
    console.log("=== All Issue #37 Scale Calibration & Route Measurement E2E Checks Passed Successfully! ===");
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
