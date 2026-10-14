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

    // Wait for takeoff calculation
    await page.waitForFunction(
      () => document.body.innerText.includes("LIGHT") && document.body.innerText.includes("OUTLET"),
      { timeout: 8000 }
    );
    await new Promise((r) => setTimeout(r, 1000));

    // Screenshot 2: Manual Markers on Image & Takeoff Table
    const shot2 = path.join(SCREENSHOTS_DIR, "13_image_takeoff_calculated.png");
    await page.screenshot({ path: shot2, fullPage: false });
    console.log(`  ✓ Captured: ${shot2}`);

    // Step 4: Open Review Drawer by clicking marker or evidence row
    console.log("[4/6] Inspecting manual marker evidence in Review Drawer...");
    const markerTarget = await page.$('.interactive-marker');
    if (markerTarget) {
      await markerTarget.click();
      await new Promise((r) => setTimeout(r, 800));
    }

    // Screenshot 3: Review Drawer Opened for Manual Marker
    const shot3 = path.join(SCREENSHOTS_DIR, "14_image_review_drawer_opened.png");
    await page.screenshot({ path: shot3, fullPage: false });
    console.log(`  ✓ Captured: ${shot3}`);

    // Step 5: Verify Exports
    console.log("[5/6] Verifying CSV & XLSX export responses...");
    const csvSummaryValid = await page.evaluate(async () => {
      const a = document.querySelector('a[href*="type=summary"]');
      if (!a) return false;
      const res = await fetch(a.href);
      const text = await res.text();
      return text.includes("LIGHT") && text.includes("MANUAL");
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

    if (!csvSummaryValid || !csvEvidenceValid) {
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
