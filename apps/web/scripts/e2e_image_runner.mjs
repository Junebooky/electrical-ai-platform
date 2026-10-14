import puppeteer from "puppeteer-core";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "../../..");

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
      : [
          "/usr/bin/google-chrome",
          "/usr/bin/google-chrome-stable",
          "/usr/bin/chromium",
          "/usr/bin/chromium-browser",
        ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error("System Chrome executable not found.");
}

const CHROME_PATH = resolveChromePath();
const BASE_URL = process.env.BASE_URL || "http://localhost:3000";
const SCREENSHOTS_DIR = path.resolve(ROOT_DIR, "docs/screenshots");
const FIXTURE_PNG = path.resolve(ROOT_DIR, "fixtures/images/floorplan_sample.png");

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

async function run() {
  console.log("=== Issue #12 PR A: Image Drawing E2E Smoke Test ===");
  console.log(`Connecting to Chrome: ${CHROME_PATH}`);
  console.log(`Testing URL: ${BASE_URL}`);
  console.log(`Fixture Image: ${FIXTURE_PNG}`);

  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--window-size=1440,900",
    ],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  try {
    // Step 1: Open landing page
    console.log("[1/6] Navigating to platform...");
    await page.goto(BASE_URL, { waitUntil: "networkidle0", timeout: 15000 });
    await new Promise((r) => setTimeout(r, 1000));

    // Step 2: Upload PNG drawing
    console.log("[2/6] Uploading 2D PNG electrical drawing...");
    const fileInput = await page.$('input[type="file"]');
    if (!fileInput) throw new Error("File input not found");
    await fileInput.uploadFile(FIXTURE_PNG);

    // Wait for drawing to appear
    await page.waitForFunction(
      () => document.body.innerText.includes("floorplan_sample.png"),
      { timeout: 10000 }
    );
    await new Promise((r) => setTimeout(r, 1500));

    // Screenshot 1: Image Loaded in Viewer
    const shot1 = path.join(SCREENSHOTS_DIR, "12_image_drawing_loaded.png");
    await page.screenshot({ path: shot1, fullPage: false });
    console.log(`  ✓ Captured: ${shot1}`);

    // Step 3: Activate Manual Add Mode and Add Markers
    console.log("[3/6] Adding manual equipment markers on image pixel coordinates...");
    // Find and click "누락 기구 수동 추가" button
    const manualBtn = await page.waitForSelector("button::-p-text(누락 기구 수동 추가)", { timeout: 5000 });
    await manualBtn.click();
    await new Promise((r) => setTimeout(r, 600));

    // Helper to click canvas at client coords and confirm modal
    async function addMarkerAt(clientOffsetX, clientOffsetY, code) {
      // Find canvas container
      const container = await page.$(".relative.w-full.h-full.overflow-hidden");
      const box = await container.boundingBox();
      const clickX = box.x + clientOffsetX;
      const clickY = box.y + clientOffsetY;

      await page.mouse.click(clickX, clickY);
      await new Promise((r) => setTimeout(r, 600));

      // Wait for modal item select
      await page.waitForSelector("#manual-item-select", { timeout: 4000 });
      await page.select("#manual-item-select", code);

      // Select reason (mandatory)
      await page.select("#manual-reason-select", "도면 누락");

      const confirmBtn = await page.waitForSelector('button[type="submit"]');
      await confirmBtn.click();
      await new Promise((r) => setTimeout(r, 800));
    }

    // Add Marker 1: LIGHT at center-left
    await addMarkerAt(300, 260, "LIGHT");
    console.log("  ✓ Added LIGHT marker 1");

    // Re-click manual button if it toggled off or keep active
    const btnText = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll("button"));
      const b = btns.find((el) => el.innerText.includes("누락 기구 수동 추가"));
      return b ? b.className : "";
    });
    if (!btnText.includes("bg-amber-500")) {
      const b = await page.waitForSelector("button::-p-text(누락 기구 수동 추가)");
      await b.click();
      await new Promise((r) => setTimeout(r, 400));
    }

    // Add Marker 2: LIGHT at center-right
    await addMarkerAt(600, 260, "LIGHT");
    console.log("  ✓ Added LIGHT marker 2");

    // Add Marker 3: OUTLET at left wall
    const b2 = await page.waitForSelector("button::-p-text(누락 기구 수동 추가)");
    await b2.click();
    await new Promise((r) => setTimeout(r, 400));
    await addMarkerAt(220, 260, "OUTLET");
    console.log("  ✓ Added OUTLET marker");

    // Add Marker 4: SWITCH at doorway
    const b3 = await page.waitForSelector("button::-p-text(누락 기구 수동 추가)");
    await b3.click();
    await new Promise((r) => setTimeout(r, 400));
    await addMarkerAt(450, 340, "SWITCH");
    console.log("  ✓ Added SWITCH marker");

    // Test Out-of-bounds Defense (HIGH-2 criteria)
    console.log("  [Defense] Testing out-of-bounds click rejection...");
    const b4 = await page.waitForSelector("button::-p-text(누락 기구 수동 추가)");
    await b4.click();
    await new Promise((r) => setTimeout(r, 400));
    const container = await page.$(".relative.w-full.h-full.overflow-hidden");
    const cBox = await container.boundingBox();
    // Click outside top-left margin (e.g., inside container near extreme corner outside SVG image)
    // Zoom in or pan, or click at container edge x=5, y=5 where pixel coords are negative
    await page.mouse.click(cBox.x + 5, cBox.y + 5);
    await new Promise((r) => setTimeout(r, 600));
    // Verify modal does NOT open and error/status warns user
    const modalExists = await page.$("#manual-item-select");
    if (modalExists) {
      throw new Error("Out-of-bounds click erroneously opened manual item modal!");
    }
    console.log("  ✓ Out-of-bounds click safely ignored/blocked.");

    // Wait for takeoff calculation
    await page.waitForFunction(
      () => document.body.innerText.includes("LIGHT") && document.body.innerText.includes("OUTLET"),
      { timeout: 8000 }
    );
    await new Promise((r) => setTimeout(r, 1000));

    // Assert exact quantities in Takeoff Table
    const quantities = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      const map = {};
      for (const row of rows) {
        const cells = Array.from(row.querySelectorAll("td")).map((c) => c.innerText.trim());
        if (cells.length >= 4) {
          const match = cells[3].match(/^(\d+)\s*(\S+)?/);
          const qty = match ? parseInt(match[1], 10) : 0;
          const unit = match && match[2] ? match[2] : "EA";
          map[cells[0]] = { name: cells[1], unit: unit, qty: qty };
        }
      }
      return map;
    });

    console.log("  ✓ Takeoff Table Quantities:", JSON.stringify(quantities));
    if (quantities["LIGHT"]?.qty !== 2) throw new Error(`Expected LIGHT qty 2, got ${quantities["LIGHT"]?.qty}`);
    if (quantities["OUTLET"]?.qty !== 1) throw new Error(`Expected OUTLET qty 1, got ${quantities["OUTLET"]?.qty}`);
    if (quantities["SWITCH"]?.qty !== 1) throw new Error(`Expected SWITCH qty 1, got ${quantities["SWITCH"]?.qty}`);
    if (quantities["LIGHT"]?.unit !== "EA") throw new Error(`Expected unit EA, got ${quantities["LIGHT"]?.unit}`);

    // Screenshot 2: Manual Markers on Image & Takeoff Table
    const shot2 = path.join(SCREENSHOTS_DIR, "13_image_takeoff_calculated.png");
    await page.screenshot({ path: shot2, fullPage: false });
    console.log(`  ✓ Captured: ${shot2}`);

    // Step 4: Open Review Drawer by clicking marker or evidence row
    console.log("[4/6] Inspecting manual marker evidence in Review Drawer...");
    const markerTarget = await page.$(".interactive-marker");
    if (markerTarget) {
      await markerTarget.click();
      await new Promise((r) => setTimeout(r, 800));
    }

    const drawerCoordText = await page.evaluate(() => document.body.innerText);
    if (!drawerCoordText.includes("이미지 좌표 (px)")) {
      throw new Error("ReviewDrawer did not show '이미지 좌표 (px)' label for image drawing!");
    }
    console.log("  ✓ Review Drawer correctly displayed '이미지 좌표 (px)'");

    // Screenshot 3: Review Drawer Opened for Manual Marker
    const shot3 = path.join(SCREENSHOTS_DIR, "14_image_review_drawer_opened.png");
    await page.screenshot({ path: shot3, fullPage: false });
    console.log(`  ✓ Captured: ${shot3}`);

    // Step 5: Verify Exports (CSV Summary, CSV Evidence, XLSX)
    console.log("[5/6] Verifying CSV & XLSX export responses...");
    const csvSummaryValid = await page.evaluate(async () => {
      const a = document.querySelector('a[href*="type=summary"]');
      if (!a) return false;
      const res = await fetch(a.href);
      const text = await res.text();
      return text.includes("LIGHT") && text.includes("MANUAL") && text.includes("EA,2");
    });
    console.log(`  ✓ CSV Summary validation: ${csvSummaryValid ? "PASS" : "FAIL"}`);

    const csvEvidenceValid = await page.evaluate(async () => {
      const a = document.querySelector('a[href*="type=evidence"]');
      if (!a) return false;
      const res = await fetch(a.href);
      const text = await res.text();
      return text.includes("MANUAL_POINT") && text.includes("LIGHT");
    });
    console.log(`  ✓ CSV Evidence validation: ${csvEvidenceValid ? "PASS" : "FAIL"}`);

    const xlsxValid = await page.evaluate(async () => {
      const a = document.querySelector('a[href*="/export/xlsx"]');
      if (!a) return false;
      const res = await fetch(a.href);
      const blob = await res.blob();
      return res.status === 200 && blob.size > 2000;
    });
    console.log(`  ✓ XLSX Export validation: ${xlsxValid ? "PASS" : "FAIL"}`);

    if (!csvSummaryValid || !csvEvidenceValid || !xlsxValid) {
      throw new Error("Export verification failed");
    }

    // Step 6: Reload Page and Verify Persistence
    console.log("[6/6] Reloading page to verify persistence...");
    await page.reload({ waitUntil: "networkidle0" });
    await new Promise((r) => setTimeout(r, 1500));

    await page.waitForFunction(
      () => document.body.innerText.includes("floorplan_sample.png") && document.body.innerText.includes("LIGHT"),
      { timeout: 10000 }
    );

    // Verify persisted marker count is exactly 4
    const reloadedMarkers = await page.evaluate(() => {
      return document.querySelectorAll(".interactive-marker").length;
    });
    console.log(`  ✓ Persisted interactive markers count: ${reloadedMarkers}`);
    if (reloadedMarkers !== 4) {
      throw new Error(`Expected 4 persisted markers, found ${reloadedMarkers}`);
    }

    // Screenshot 4: Reload Persistence Verified
    const shot4 = path.join(SCREENSHOTS_DIR, "15_image_reload_persistence.png");
    await page.screenshot({ path: shot4, fullPage: false });
    console.log(`  ✓ Captured: ${shot4}`);

    console.log("=== All 6/6 Image Drawing E2E Steps PASSED! ===");
  } finally {
    await browser.close();
  }
}

run().catch((err) => {
  console.error("E2E Test Failed:", err);
  process.exit(1);
});
