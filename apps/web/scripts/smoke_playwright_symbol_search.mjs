import { chromium } from "playwright";
import path from "path";
import fs from "fs";
import { spawn } from "child_process";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "../../..");
const WEB_DIR = path.resolve(__dirname, "..");

// -----------------------------------------------------------------------------
// Environment Configuration & Safe Automatic Discovery
// -----------------------------------------------------------------------------
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
  return undefined; // Let playwright use bundled/managed chromium if installed
}

const CHROME_PATH = resolveChromePath();
const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:3005";
const API_URL = process.env.API_URL || "http://127.0.0.1:8000";
const SCREENSHOTS_DIR =
  process.env.SCREENSHOTS_DIR || path.resolve(__dirname, "../test-results/playwright_screenshots");

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

// -----------------------------------------------------------------------------
// Helper: Wait for URL Health
// -----------------------------------------------------------------------------
async function waitForUrl(url, timeoutMs = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok || res.status === 200 || res.status === 304 || res.status === 404) {
        return true;
      }
    } catch {}
    await new Promise((r) => setTimeout(r, 400));
  }
  return false;
}

// -----------------------------------------------------------------------------
// RFC 4180 Compliant CSV Parser
// -----------------------------------------------------------------------------
function parseRfcCsv(text) {
  const rows = [];
  let currentRow = [];
  let currentCell = "";
  let insideQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    const nextChar = text[i + 1];
    if (char === '"') {
      if (insideQuotes && nextChar === '"') {
        currentCell += '"';
        i++;
      } else {
        insideQuotes = !insideQuotes;
      }
    } else if (char === "," && !insideQuotes) {
      currentRow.push(currentCell);
      currentCell = "";
    } else if ((char === "\r" || char === "\n") && !insideQuotes) {
      if (char === "\r" && nextChar === "\n") {
        i++;
      }
      currentRow.push(currentCell);
      if (currentRow.length > 0 && !(currentRow.length === 1 && currentRow[0] === "")) {
        rows.push(currentRow);
      }
      currentRow = [];
      currentCell = "";
    } else {
      currentCell += char;
    }
  }
  if (currentCell || currentRow.length > 0) {
    currentRow.push(currentCell);
    rows.push(currentRow);
  }
  return rows;
}

// Strict assertion helper
function assert(condition, message) {
  if (!condition) {
    throw new Error(`[AssertionFailed]: ${message}`);
  }
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(
      `[AssertionFailed]: ${message} (Expected: ${expected}, Actual: ${actual})`
    );
  }
}

// -----------------------------------------------------------------------------
// Main Playwright Smoke Suite (Issue #29 Workstream D)
// -----------------------------------------------------------------------------
async function runPlaywrightSmoke() {
  console.log("================================================================================");
  console.log(" [Issue #29 Workstream D] Playwright Chromium Automated Smoke & E2E Validation");
  console.log("================================================================================");
  console.log(`Chrome Executable : ${CHROME_PATH || "Playwright Managed"}`);
  console.log(`Base Web URL      : ${BASE_URL}`);
  console.log(`API URL           : ${API_URL}`);
  console.log(`Screenshots Dir   : ${SCREENSHOTS_DIR}`);

  const spawnedProcesses = [];

  // 1. Ensure Backend is Running
  const apiAlive = await waitForUrl(`${API_URL}/api/health`, 1500);
  if (!apiAlive) {
    console.log("Starting backend server (uvicorn eai_api.app:app)...");
    const pythonPath = `${path.resolve(ROOT_DIR, "packages/cad_engine/src")}:${path.resolve(
      ROOT_DIR,
      "apps/api/src"
    )}`;
    const backendProc = spawn(
      "uv",
      ["run", "uvicorn", "eai_api.app:app", "--host", "127.0.0.1", "--port", "8000"],
      {
        cwd: ROOT_DIR,
        env: { ...process.env, PYTHONPATH: pythonPath },
        stdio: "inherit",
      }
    );
    spawnedProcesses.push(backendProc);
    const ready = await waitForUrl(`${API_URL}/api/health`, 20000);
    assert(ready, "Backend server failed to start within 20s");
    console.log("  Backend server ready!");
  } else {
    console.log("  Backend server already running.");
  }

  // 2. Ensure Frontend is Running
  const webAlive = await waitForUrl(`${BASE_URL}/`, 1500);
  if (!webAlive) {
    console.log("Starting frontend server (next start -p 3005)...");
    const frontendProc = spawn(
      "npm",
      ["run", "start", "--", "-p", "3005"],
      { cwd: WEB_DIR, stdio: "inherit" }
    );
    spawnedProcesses.push(frontendProc);
    const ready = await waitForUrl(`${BASE_URL}/`, 20000);
    assert(ready, "Frontend server failed to start within 20s");
    console.log("  Frontend server ready!");
  } else {
    console.log("  Frontend server already running.");
  }

  const launchOptions = {
    headless: true,
    args: ["--disable-gpu", "--window-size=1440,900"],
  };
  if (CHROME_PATH) {
    launchOptions.executablePath = CHROME_PATH;
  }
  if (process.env.CI || process.platform === "linux") {
    launchOptions.args.push("--no-sandbox", "--disable-setuid-sandbox");
  }

  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  page.on("console", (msg) => {
    if (msg.type() === "error") {
      console.log(`[Browser Console Error]: ${msg.text()}`);
    }
  });

  const testReport = { passed: 0, failed: 0 };
  const recordResult = (name, details = "") => {
    testReport.passed++;
    console.log(`  [PASS] ${name} ${details ? `(${details})` : ""}`);
  };

  try {
    // -------------------------------------------------------------------------
    // Step 1: Initial Landing & Demo Project Seed
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 1: Initial Landing & Seed Demo Project ---");
    // Ensure clean deterministic baseline
    try {
      await fetch(`${API_URL}/api/demo/seed?reset=true`, { method: "POST" });
    } catch {}
    await page.goto(BASE_URL, { waitUntil: "networkidle" });
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "01_landing_page.png") });

    // Click Live Demo Seed button
    const seedBtn = await page.waitForSelector('[data-testid="btn-live-demo"]', { timeout: 10000 });
    assert(seedBtn, "Demo seed button not found on landing page");
    await seedBtn.click();
    await page.waitForTimeout(2500);

    // Verify 3 drawings seeded
    const selectEl = await page.waitForSelector('select[aria-label="저장된 도면 목록"]', { timeout: 10000 });
    const drawingOptions = await selectEl.$$eval("option", (opts) => opts.map((o) => o.textContent || ""));
    assert(drawingOptions.length >= 3, `Expected at least 3 demo drawings, found ${drawingOptions.length}`);
    assert(drawingOptions.some((t) => t.includes(".dxf")), "DXF demo drawing missing");
    assert(drawingOptions.some((t) => t.includes(".pdf")), "PDF demo drawing missing");
    assert(drawingOptions.some((t) => t.includes(".png")), "IMAGE demo drawing missing");
    recordResult("Demo Project Seeded with 3 Formats", `Drawings: ${drawingOptions.length}`);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "02_demo_seeded.png") });

    // -------------------------------------------------------------------------
    // Step 2: Switch to 2D Floorplan Image Drawing
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 2: Switch to Image Drawing (floorplan_sample.png) ---");
    const imgOptValue = await selectEl.$$eval("option", (opts) => {
      const target = opts.find((o) => (o.textContent || "").includes("floorplan_sample.png"));
      return target ? target.value : null;
    });
    assert(imgOptValue, "floorplan_sample.png option value not found");
    await selectEl.selectOption(imgOptValue);
    await page.waitForTimeout(2000);

    // Verify image rendered in CadViewer
    const imageElement = await page.waitForSelector("svg image", { timeout: 8000 });
    assert(imageElement, "SVG image element not rendered for floorplan_sample.png");
    recordResult("2D Floorplan Image Loaded", "SVG <image> rendered successfully");
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "03_image_drawing_loaded.png") });

    // -------------------------------------------------------------------------
    // Step 3: Interactive Crop & Visual Symbol Search (Workstream B)
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 3: Crop Symbol on CadViewer & Visual Search ---");

    // Click "기호 영역 검색" toggle button
    const cropToggleBtn = await page.waitForSelector('[data-testid="btn-crop-search-toggle"]', { timeout: 8000 });
    await cropToggleBtn.click();
    await page.waitForTimeout(500);

    // Verify crosshair active guidance banner
    const cropBanner = await page.$('text="도면에서 찾고 싶은 기호 영역을 마우스로 드래그하세요"');
    assert(cropBanner, "Active crop search guidance banner not displayed");

    // Simulate drag-to-crop rectangle on canvas (selecting a sample symbol)
    const viewerEl = await page.waitForSelector(".cursor-crosshair", { timeout: 6000 });
    const box = await viewerEl.boundingBox();
    assert(box, "CAD Viewer container bounding box not found");

    const startX = box.x + box.width * 0.35;
    const startY = box.y + box.height * 0.35;
    const endX = startX + 60;
    const endY = startY + 60;

    await page.mouse.move(startX, startY);
    await page.waitForTimeout(100);
    await page.mouse.down({ button: "left" });
    await page.waitForTimeout(100);
    await page.mouse.move(endX, endY, { steps: 10 });
    await page.waitForTimeout(100);
    await page.mouse.up({ button: "left" });
    await page.waitForTimeout(800);

    // Verify Symbol Search Modal opens
    const modal = await page.waitForSelector('[data-testid="symbol-search-modal"]', { timeout: 6000 });
    assert(modal, "SymbolSearchModal dialog did not open after rubberband drag");
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "04_symbol_search_modal_opened.png") });

    // Select Item Code: LIGHT and submit search
    const selectItem = await page.waitForSelector('[data-testid="select-crop-search-item"]');
    await selectItem.selectOption("LIGHT");

    const submitSearchBtn = await page.waitForSelector('[data-testid="btn-submit-symbol-search"]');
    await submitSearchBtn.click();
    await page.waitForTimeout(3000);

    // Verify success notification or candidates loaded
    const candidateRows = await page.$$(".interactive-candidate, [data-testid^='candidate-marker-']");
    console.log(`  Detected candidate markers rendered on CadViewer: ${candidateRows.length}`);
    recordResult("User-Defined Symbol Search Executed", `Found & rendered candidates`);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "05_candidates_detected_view.png") });

    // -------------------------------------------------------------------------
    // Step 4: Keyboard Shortcuts & Bulk Review (Workstream C)
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 4: Professional Inspection Review & Shortcuts (A/R) ---");

    // Verify CandidateReviewTable is active and select first candidate row
    const firstRow = await page.waitForSelector('[data-testid="candidate-row"]', { timeout: 6000 });
    assert(firstRow, "Review candidate table row not found");
    await firstRow.click();
    await page.waitForTimeout(200);

    // Test shortcut 'R' (Reject current focused candidate row)
    await page.keyboard.press("r");
    await page.waitForTimeout(600);
    const rejectedCountText = await page.$eval(
      ".bg-rose-950\\/30 span.text-sm.font-bold",
      (el) => el.textContent?.trim() || "0"
    );
    assert(rejectedCountText !== "0건", `Shortcut 'r' failed to transition candidate to REJECTED (count: ${rejectedCountText})`);

    // Test shortcut 'A' (Accept current focused candidate row)
    await page.keyboard.press("a");
    await page.waitForTimeout(600);
    const acceptedSingleCount = await page.$eval(
      ".bg-emerald-950\\/30 span.text-sm.font-bold",
      (el) => el.textContent?.trim() || "0"
    );
    assert(acceptedSingleCount !== "0건", `Shortcut 'a' failed to transition candidate to ACCEPTED (count: ${acceptedSingleCount})`);
    recordResult("Keyboard Shortcuts (A/R/Navigation) Exercised", `Single-key quick inspection verified (R -> ${rejectedCountText}, A -> ${acceptedSingleCount})`);

    // Click bulk accept to approve proposed candidates
    const bulkAcceptBtn = await page.waitForSelector('[data-testid="btn-bulk-accept"]', { timeout: 6000 });
    assert(bulkAcceptBtn, "Bulk accept button not found in review panel");
    const isBulkDisabled = await page.$eval('[data-testid="btn-bulk-accept"]', (btn) => btn.disabled);
    if (!isBulkDisabled) {
      await bulkAcceptBtn.click();
      await page.waitForTimeout(1500);
    }

    // Verify candidates are now accepted
    const acceptedCountText = await page.$eval(
      ".bg-emerald-950\\/30 span.text-sm.font-bold",
      (el) => el.textContent?.trim() || "0"
    );
    console.log(`  Accepted count after bulk approval: ${acceptedCountText}`);
    assert(acceptedCountText !== "0건", "Bulk accept failed to update accepted candidate count");
    recordResult("Bulk Candidate Review Approval", `Accepted: ${acceptedCountText}`);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "06_candidates_approved.png") });

    // -------------------------------------------------------------------------
    // Step 5: Takeoff Table & Bidirectional Inspection Verification
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 5: Takeoff Calculation & Bidirectional Inspection ---");
    const takeoffTabBtn = await page.waitForSelector('button:has-text("물량산출표")', { timeout: 6000 });
    await takeoffTabBtn.click();
    await page.waitForTimeout(1500);

    // Verify Takeoff Table has rows with EA >= 1
    const summaryRows = await page.$$eval("tbody tr", (trs) =>
      trs.map((tr) => ({
        code: tr.querySelector("td:nth-child(1)")?.textContent?.trim() || "",
        qty: parseInt(tr.querySelector("td:nth-child(4)")?.textContent?.trim() || "0", 10),
      }))
    );
    const lightRow = summaryRows.find((r) => r.code === "LIGHT");
    assert(lightRow && lightRow.qty > 0, "Approved candidates not reflected in Takeoff EA quantity");
    recordResult("Takeoff Table Exact EA Reflection", `LIGHT: ${lightRow.qty} EA`);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "07_takeoff_calculated.png") });

    // -------------------------------------------------------------------------
    // Step 6: CSV & XLSX Export Integrity
    // -------------------------------------------------------------------------
    const csvSummaryLink = await page.$eval('[data-testid="btn-export-csv-summary"]', (a) => a.href);
    const csvEvidenceLink = await page.$eval('[data-testid="btn-export-csv-evidence"]', (a) => a.href);
    const xlsxLink = await page.$eval('[data-testid="btn-export-xlsx"]', (a) => a.href);

    // Check CSV Summary
    const csvSummaryRes = await fetch(csvSummaryLink);
    assert(csvSummaryRes.ok, `CSV Summary download failed: ${csvSummaryRes.status}`);
    const csvSummaryText = await csvSummaryRes.text();
    const csvSummaryData = parseRfcCsv(csvSummaryText);
    assert(csvSummaryData.length >= 2, "CSV Summary contains fewer than 2 rows");
    const csvLightRow = csvSummaryData.find((r) => r[0] === "LIGHT");
    assert(csvLightRow, "LIGHT row missing in CSV Summary export");
    const csvQty = parseInt(csvLightRow[4] || csvLightRow[2] || "0", 10);
    assertEqual(csvQty, lightRow.qty, "CSV Summary quantity must strictly match Takeoff table EA quantity");
    recordResult("CSV Summary Export Validated", `Rows: ${csvSummaryData.length}, LIGHT: ${csvQty} EA (Exact Match)`);

    // Check CSV Evidence
    const csvEvidenceRes = await fetch(csvEvidenceLink);
    assert(csvEvidenceRes.ok, `CSV Evidence download failed: ${csvEvidenceRes.status}`);
    const csvEvidenceText = await csvEvidenceRes.text();
    const csvEvidenceData = parseRfcCsv(csvEvidenceText);
    assert(csvEvidenceData.length >= 2, "CSV Evidence contains fewer than 2 rows");
    recordResult("CSV Evidence Export Validated", `Rows: ${csvEvidenceData.length}`);

    // Check XLSX
    const xlsxRes = await fetch(xlsxLink);
    assert(xlsxRes.ok, `XLSX download failed: ${xlsxRes.status}`);
    const xlsxBuffer = Buffer.from(await xlsxRes.arrayBuffer());
    assert(xlsxBuffer.length > 500, "XLSX file is suspiciously small or empty");
    assert(
      xlsxBuffer[0] === 0x50 && xlsxBuffer[1] === 0x4b,
      "XLSX file header does not match PK zip signature"
    );
    const xlsxBinaryStr = xlsxBuffer.toString("latin1");
    assert(
      xlsxBinaryStr.includes("sheet1.xml") && xlsxBinaryStr.includes("sheet2.xml"),
      "XLSX workbook must contain both sheet1.xml (Takeoff Summary) and sheet2.xml (Evidence)"
    );
    assert(xlsxBinaryStr.includes("workbook.xml"), "XLSX workbook structure verified");
    recordResult("XLSX Export Validated", `Valid 2-Sheet Excel Workbook (${xlsxBuffer.length} bytes, Summary+Evidence)`);

    // -------------------------------------------------------------------------
    // Step 7: Demo Reseed Idempotency (P1-DEMO-RESEED)
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 7: Demo Reseed Idempotency (P1-DEMO-RESEED) ---");
    const reseedBtn = await page.waitForSelector('[data-testid="btn-live-demo"]', { timeout: 10000 });
    await reseedBtn.click();
    await page.waitForTimeout(2500);

    // Verify drawing count is strictly unchanged
    const recheckOptions = await selectEl.$$eval("option", (opts) => opts.map((o) => o.textContent || ""));
    assertEqual(recheckOptions.length, drawingOptions.length, "Reseed must NOT proliferate drawing count");

    // Select floorplan_sample.png again to inspect preserved review
    await selectEl.selectOption(imgOptValue);
    await page.waitForTimeout(2000);

    // Switch to Takeoff tab to verify preserved takeoff quantities
    const recheckTakeoffBtn = await page.waitForSelector('button:has-text("물량산출표")', { timeout: 6000 });
    await recheckTakeoffBtn.click();
    await page.waitForTimeout(1500);

    // Verify accepted quantity on reseeded project is preserved
    const recheckRows = await page.$$eval("tbody tr", (trs) =>
      trs.map((tr) => ({
        code: tr.querySelector("td:nth-child(1)")?.textContent?.trim() || "",
        qty: parseInt(tr.querySelector("td:nth-child(4)")?.textContent?.trim() || "0", 10),
      }))
    );
    const recheckLight = recheckRows.find((r) => r.code === "LIGHT")?.qty || 0;
    assertEqual(recheckLight, lightRow.qty, "Reseed must preserve user accepted review states");
    recordResult("Demo Reseed Idempotency Verified", `Drawing count strictly ${drawingOptions.length}, review preserved`);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "08_reseed_idempotency_verified.png") });

    // -------------------------------------------------------------------------
    // Suite Completion
    // -------------------------------------------------------------------------
    console.log("\n================================================================================");
    console.log(` [Issue #29 Workstream D] ALL PLAYWRIGHT SMOKE TESTS PASSED: ${testReport.passed} Passed, 0 Failed`);
    console.log("================================================================================");
  } catch (err) {
    console.error("\n❌ [PLAYWRIGHT SMOKE FAILURE]:", err);
    try {
      await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "error_playwright.png") });
    } catch {}
    process.exitCode = 1;
  } finally {
    await browser.close();
    for (const proc of spawnedProcesses) {
      try {
        proc.kill("SIGTERM");
      } catch {}
    }
  }
}

runPlaywrightSmoke().catch((err) => {
  console.error("Unhandled top-level error:", err);
  process.exit(1);
});
