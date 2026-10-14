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
const FIXTURE_R12_MALFORMED = path.resolve(
  ROOT_DIR,
  "packages/cad_engine/tests/fixtures/r12_malformed_lwpolyline.dxf"
);
const FIXTURE_NO_INSERT = path.resolve(
  ROOT_DIR,
  "fixtures/dxf/schematic_entities_no_insert.dxf"
);

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

async function run() {
  console.log("=== Issue #15: R12 Diagnostic Error & Zero-Insert CAD E2E Test ===");
  console.log(`Connecting to Chrome: ${CHROME_PATH}`);
  console.log(`Testing URL: ${BASE_URL}`);

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
    console.log("[1/4] Navigating to platform...");
    await page.goto(BASE_URL, { waitUntil: "networkidle0", timeout: 15000 });
    await new Promise((r) => setTimeout(r, 1000));

    // Step 2: Upload malformed R12 DXF and assert diagnostic banner
    console.log("[2/4] Uploading malformed R12 DXF (LWPOLYLINE without AcDbPolyline)...");
    const fileInput1 = await page.$('input[type="file"]');
    if (!fileInput1) throw new Error("File input not found");
    await fileInput1.uploadFile(FIXTURE_R12_MALFORMED);

    // Wait for global error banner
    console.log("  Waiting for diagnostic error banner...");
    const bannerSelector = "#global-error-banner";
    await page.waitForSelector(bannerSelector, { timeout: 8000 });
    const bannerText = await page.$eval(bannerSelector, (el) => el.innerText);

    console.log("  ✓ Diagnostic Banner Content:\n    ", bannerText.replace(/\n/g, " "));

    // Assert key diagnostic elements
    if (!bannerText.includes("AutoCAD R12(AC1009)")) {
      throw new Error("Missing 'AutoCAD R12(AC1009)' in diagnostic banner");
    }
    if (!bannerText.includes("LWPOLYLINE")) {
      throw new Error("Missing 'LWPOLYLINE' in diagnostic banner");
    }
    if (!bannerText.includes("AcDbPolyline")) {
      throw new Error("Missing 'AcDbPolyline' in diagnostic banner");
    }
    if (!bannerText.includes("AutoCAD 2000 DXF(AC1015)")) {
      throw new Error("Missing 'AutoCAD 2000 DXF(AC1015)' in diagnostic banner");
    }

    // Capture Screenshot 16
    const shot1 = path.join(SCREENSHOTS_DIR, "16_r12_malformed_diagnostic_banner.png");
    await page.screenshot({ path: shot1, fullPage: false });
    console.log(`  ✓ Captured: ${shot1}`);

    // Step 3: Dismiss banner
    const closeBtn = await page.$('#global-error-banner button');
    if (closeBtn) await closeBtn.click();
    await new Promise((r) => setTimeout(r, 500));

    // Step 4: Upload standard AutoCAD 2000 DXF with 0 INSERT entities
    console.log("[3/4] Uploading valid AC1015 DXF with 0 INSERT blocks...");
    const fileInput2 = await page.$('input[type="file"]');
    await fileInput2.uploadFile(FIXTURE_NO_INSERT);

    // Wait for drawing to appear in header
    await page.waitForFunction(
      () => document.body.innerText.includes("schematic_entities_no_insert.dxf"),
      { timeout: 10000 }
    );
    await new Promise((r) => setTimeout(r, 1200));

    // Click on "블록 매핑" tab
    console.log("[4/4] Verifying empty state in Block Mapping tab...");
    const mappingTab = await page.waitForSelector("button::-p-text(블록 매핑)");
    await mappingTab.click();
    await new Promise((r) => setTimeout(r, 800));

    // Verify empty state text
    const emptyStateText = await page.evaluate(() => document.body.innerText);
    if (!emptyStateText.includes("자동 집계 가능한 CAD 블록 없음")) {
      throw new Error("Expected '자동 집계 가능한 CAD 블록 없음' in empty state");
    }
    if (!emptyStateText.includes("기본 엔티티로만 구성된 도면입니다")) {
      throw new Error("Expected entities explanation in empty state");
    }
    console.log("  ✓ Empty state verified: '자동 집계 가능한 CAD 블록 없음'");

    // Capture Screenshot 17
    const shot2 = path.join(SCREENSHOTS_DIR, "17_schematic_entities_no_insert_empty_state.png");
    await page.screenshot({ path: shot2, fullPage: false });
    console.log(`  ✓ Captured: ${shot2}`);

    console.log("=== All Issue #15 E2E Verification Steps PASSED! ===");
  } finally {
    await browser.close();
  }
}

run().catch((err) => {
  console.error("Issue #15 Test Failed:", err);
  process.exit(1);
});
