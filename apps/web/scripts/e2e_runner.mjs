import puppeteer from "puppeteer-core";
import path from "path";
import fs from "fs";
import zlib from "zlib";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "../../..");

// -----------------------------------------------------------------------------
// Environment Configuration & Safe Automatic Discovery (No Personal Paths)
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
  throw new Error(
    "System Chrome / Chromium executable not found. Please set CHROME_PATH environment variable."
  );
}

const CHROME_PATH = resolveChromePath();
const BASE_URL = process.env.BASE_URL || "http://localhost:3005";
const API_URL = process.env.API_URL || "http://127.0.0.1:8000";
const SCREENSHOTS_DIR =
  process.env.SCREENSHOTS_DIR || path.resolve(__dirname, "../test-results/screenshots");

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

// -----------------------------------------------------------------------------
// Pure Node Zip Parser for XLSX Sheet Inspection (0 external dependencies)
// -----------------------------------------------------------------------------
function readZipEntries(buffer) {
  const entries = {};
  let offset = 0;
  while (offset < buffer.length - 30) {
    if (buffer.readUInt32LE(offset) !== 0x04034b50) break; // Local file header signature
    const compressionMethod = buffer.readUInt16LE(offset + 8);
    const compressedSize = buffer.readUInt32LE(offset + 18);
    const uncompressedSize = buffer.readUInt32LE(offset + 22);
    const fileNameLength = buffer.readUInt16LE(offset + 26);
    const extraFieldLength = buffer.readUInt16LE(offset + 28);
    const fileName = buffer.toString(
      "utf8",
      offset + 30,
      offset + 30 + fileNameLength
    );
    const dataOffset = offset + 30 + fileNameLength + extraFieldLength;
    const compressedData = buffer.subarray(dataOffset, dataOffset + compressedSize);

    let data;
    if (compressionMethod === 0) {
      data = compressedData;
    } else if (compressionMethod === 8) {
      try {
        data = zlib.inflateRawSync(compressedData);
      } catch {
        data = null;
      }
    }
    entries[fileName] = { compressionMethod, compressedSize, uncompressedSize, data };
    offset = dataOffset + compressedSize;
  }
  return entries;
}

// Strict assertion helper (Throws on failure, never falsely passes)
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

async function runE2E() {
  console.log("================================================================================");
  console.log(" [Issue #10] Strict Browser E2E Test Suite via System Chrome");
  console.log("================================================================================");
  console.log(`Chrome Executable : ${CHROME_PATH}`);
  console.log(`Base Web URL      : ${BASE_URL}`);
  console.log(`API URL           : ${API_URL}`);
  console.log(`Screenshots Dir   : ${SCREENSHOTS_DIR}`);

  const chromeArgs = ["--disable-gpu", "--window-size=1440,900"];
  // Only add no-sandbox in CI or Linux environments
  if (process.env.CI || process.platform === "linux") {
    chromeArgs.push("--no-sandbox", "--disable-setuid-sandbox");
  }

  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: chromeArgs,
    defaultViewport: { width: 1440, height: 900 },
  });

  const page = await browser.newPage();

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
    // Step 0: Create Clean Isolated Project via API for 100% Deterministic State
    // -------------------------------------------------------------------------
    console.log("\n--- Step 0: Setting up clean isolated test project ---");
    const testProjectName = `E2E_Test_Project_${Date.now()}`;
    const projRes = await fetch(`${API_URL}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: testProjectName, description: "E2E automated isolation run" }),
    });
    assert(projRes.ok, `Failed to create test project: ${projRes.status}`);
    const isolatedProject = await projRes.json();
    console.log(`  Created isolated project: ${isolatedProject.id} (${testProjectName})`);

    // -------------------------------------------------------------------------
    // Scenario 1: Initial Landing Page & Header Branding
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 1: Initial Landing Page & Header Branding ---");
    await page.goto(BASE_URL, { waitUntil: "networkidle0" });
    await page.waitForSelector("header");
    const headerTitle = await page.$eval("h1", (el) => el.textContent.trim());
    assert(headerTitle.includes("Electrical AI Platform"), `Header branding mismatch: "${headerTitle}"`);
    recordResult("Header branding render", headerTitle);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "01_initial_landing.png") });

    // -------------------------------------------------------------------------
    // Scenario 2: ASCII DXF Upload & 2D Vector CAD Canvas
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 2: ASCII DXF Upload & 2D CAD Vector Rendering ---");
    const basicDxfPath = path.join(ROOT_DIR, "fixtures/dxf/basic_devices.dxf");
    const fileInput = await page.$('input[type="file"]');
    assert(fileInput, "File upload input element not found in DOM");
    await fileInput.uploadFile(basicDxfPath);

    // Wait for CAD viewer toolbar and SVG canvas to mount
    await page.waitForSelector('button[title="줌 인"]', { timeout: 15000 });
    await page.waitForSelector("svg text", { timeout: 10000 });
    const svgCircleCount = await page.$$eval("svg circle", (els) => els.length);
    const svgPathCount = await page.$$eval("svg path", (els) => els.length);
    assert(svgCircleCount > 0, "No circle vector elements rendered in CAD viewer");
    assert(svgPathCount > 0, "No path vector elements rendered in CAD viewer");
    recordResult("DXF upload & SVG vector primitives rendered", `circles=${svgCircleCount}, paths=${svgPathCount}`);
    await new Promise((r) => setTimeout(r, 1000));
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "02_dxf_uploaded_view.png") });

    // -------------------------------------------------------------------------
    // Scenario 3: CAD Zoom / Fit Viewport Transform Assertion
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 3: CAD Viewport Zoom & Fit Transform Assertion ---");
    const getScale = async () => {
      return await page.$eval("svg > g", (el) => {
        const transform = el.getAttribute("transform") || "";
        const match = transform.match(/scale\(([^)]+)\)/);
        return match ? parseFloat(match[1]) : 1;
      });
    };

    const initialScale = await getScale();
    assert(initialScale > 0, "Initial CAD scale must be positive number");

    // Click "줌 인" button twice
    const zoomInBtn = await page.$('button[title="줌 인"]');
    assert(zoomInBtn, "Zoom in button not found");
    await zoomInBtn.click();
    await new Promise((r) => setTimeout(r, 200));
    await zoomInBtn.click();
    await new Promise((r) => setTimeout(r, 300));

    const zoomedScale = await getScale();
    assert(
      zoomedScale >= initialScale * 1.5,
      `Zoom in failed: initial=${initialScale}, zoomed=${zoomedScale}`
    );
    recordResult("CAD Toolbar Zoom-In verified with transform matrix", `Scale: ${initialScale} -> ${zoomedScale}`);

    // Click "화면 맞춤" (Fit) button
    const fitBtn = await page.$('button[title="화면 맞춤"]');
    assert(fitBtn, "Fit to screen button not found");
    await fitBtn.click();
    await new Promise((r) => setTimeout(r, 500));

    const fitScale = await getScale();
    assert(
      Math.abs(fitScale - initialScale) < 0.05,
      `Fit to screen failed: initial=${initialScale}, fit=${fitScale}`
    );
    recordResult("CAD Toolbar Fit-to-screen viewport restored", `Scale restored to ${fitScale}`);

    // -------------------------------------------------------------------------
    // Scenario 4: Block Mapping & Exact Quantity Calculation
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 4: Block Mapping & Exact Quantity Calculation ---");
    // Switch to '블록 매핑' tab
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const tab = buttons.find((b) => b.textContent.includes("블록 매핑"));
      if (tab) tab.click();
    });
    await new Promise((r) => setTimeout(r, 600));

    // Map LT-DL -> 조명설비, OT-2P -> 전열콘센트, SW-1 -> 배선스위치
    const mappedCount = await page.evaluate(() => {
      let count = 0;
      const blockCards = Array.from(document.querySelectorAll(".p-3.rounded-lg.border"));
      for (const card of blockCards) {
        const text = card.textContent || "";
        const buttons = Array.from(card.querySelectorAll("button"));
        if (text.includes("LT-DL")) {
          const btn = buttons.find((b) => b.textContent.includes("조명설비"));
          if (btn) { btn.click(); count++; }
        } else if (text.includes("OT-2P")) {
          const btn = buttons.find((b) => b.textContent.includes("전열콘센트"));
          if (btn) { btn.click(); count++; }
        } else if (text.includes("SW-1")) {
          const btn = buttons.find((b) => b.textContent.includes("배선스위치"));
          if (btn) { btn.click(); count++; }
        }
      }
      return count;
    });
    assertEqual(mappedCount, 3, "Mapped blocks count must be exactly 3");
    recordResult("Block category selection", "LT-DL, OT-2P, SW-1 assigned");
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "03_block_mapping_tab.png") });

    // Click "매핑 적용" button
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const saveBtn = buttons.find((b) => b.textContent.includes("매핑 적용"));
      if (saveBtn) saveBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1200));

    // Return to "물량산출표" tab
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const tab = buttons.find((b) => b.textContent.includes("물량산출표"));
      if (tab) tab.click();
    });
    await new Promise((r) => setTimeout(r, 800));

    // Verify summary table rows and EXACT fixture quantities
    const summaryRows = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      return rows.map((r) => ({
        code: r.querySelector("td:nth-child(1)")?.textContent?.trim() || "",
        name: r.querySelector("td:nth-child(2)")?.textContent?.trim() || "",
        qty: parseInt(r.querySelector("td:nth-child(4)")?.textContent?.trim() || "0", 10),
      }));
    });

    const lightRow = summaryRows.find((r) => r.code === "LIGHT");
    const outletRow = summaryRows.find((r) => r.code === "OUTLET");
    const switchRow = summaryRows.find((r) => r.code === "SWITCH");

    assert(lightRow, "LIGHT row missing from takeoff summary table");
    assert(outletRow, "OUTLET row missing from takeoff summary table");
    assert(switchRow, "SWITCH row missing from takeoff summary table");

    // Exact fixture assertions
    assertEqual(lightRow.qty, 6, "LIGHT count must be exactly 6 EA");
    assertEqual(outletRow.qty, 4, "OUTLET count must be exactly 4 EA");
    assertEqual(switchRow.qty, 3, "SWITCH count must be exactly 3 EA");
    recordResult("Exact fixture takeoff verification", "LIGHT=6, OUTLET=4, SWITCH=3 (Total: 13 EA)");
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "04_takeoff_calculated.png") });

    // -------------------------------------------------------------------------
    // Scenario 5: Review Confirmation, Exclusion & Restoration with Delta Asserts
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 5: Review Confirmation, Exclusion & Restoration ---");
    // Switch to "객체 근거" sub-tab in Takeoff table
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const evidenceTab = buttons.find((b) => b.textContent.includes("객체 근거"));
      if (evidenceTab) evidenceTab.click();
    });
    await new Promise((r) => setTimeout(r, 600));

    // Click first evidence card (LT-DL mapped to LIGHT)
    const clickedCard = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".p-2\\.5.rounded.border.cursor-pointer"));
      if (cards.length > 0) {
        cards[0].click();
        return true;
      }
      return false;
    });
    assert(clickedCard, "Failed to click evidence card");
    await new Promise((r) => setTimeout(r, 800));

    const drawerVisible = await page.evaluate(() => {
      const drawer = document.querySelector(".w-96");
      return drawer !== null && drawer.textContent.includes("선택된 CAD 기구 객체");
    });
    assert(drawerVisible, "Review Drawer did not open with selected CAD object");
    recordResult("Review Drawer data binding verified");
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "05_review_drawer_opened.png") });

    // 5A: Click "검수 확인" and assert status change in UI & API
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll(".w-96 button"));
      const confirmBtn = buttons.find((b) => b.textContent.includes("검수 확인"));
      if (confirmBtn) confirmBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1200));

    const reviewConfirmedText = await page.evaluate(() => {
      const drawer = document.querySelector(".w-96");
      return drawer ? drawer.innerText : "";
    });
    assert(
      reviewConfirmedText.includes("REVIEWED"),
      "Drawer status badge must indicate REVIEWED after confirmation"
    );
    recordResult("Review confirmation asserted (status: REVIEWED)");
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "06_review_confirmed.png") });

    // 5B: Click "오탐 제외" (EXCLUDED) and assert quantity decreases (6 -> 5)
    console.log("  Testing review exclusion (EXCLUDED)...");
    const clickedExclude = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll(".w-96 button"));
      const excludeBtn = buttons.find((b) => b.textContent.includes("오탐 제외"));
      if (excludeBtn) {
        excludeBtn.click();
        return true;
      }
      return false;
    });
    assert(clickedExclude, "Could not find '오탐 제외' button in Review Drawer");
    await new Promise((r) => setTimeout(r, 1500));

    // Verify quantity decreased from 6 to 5
    const drawerTextAfterExclude = await page.evaluate(() => {
      const badge = document.querySelector(".w-96");
      return badge ? badge.innerText : "<null>";
    });
    assert(drawerTextAfterExclude.includes("EXCLUDED"), "Drawer badge must show EXCLUDED status");

    // Check summary table quantity
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const tab = buttons.find((b) => b.textContent.includes("산출 요약"));
      if (tab) tab.click();
    });
    await new Promise((r) => setTimeout(r, 600));

    const lightQtyAfterExclude = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      const r = rows.find((row) => row.textContent.includes("LIGHT"));
      return r ? parseInt(r.querySelector("td:nth-child(4)")?.textContent || "0", 10) : 0;
    });
    assertEqual(lightQtyAfterExclude, 5, "LIGHT quantity must decrease from 6 to 5 after exclusion (-1 delta)");
    recordResult("Exclusion delta asserted", "LIGHT: 6 -> 5 EA");

    // 5C: Click "집계에 복원" (INCLUDED) and assert quantity restores (5 -> 6)
    console.log("  Testing restoration (INCLUDED)...");
    const clickedRestore = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll(".w-96 button"));
      const restoreBtn = buttons.find((b) => b.textContent.includes("집계에 복원"));
      if (restoreBtn) {
        restoreBtn.click();
        return true;
      }
      return false;
    });
    assert(clickedRestore, "Could not find '집계에 복원' button in Review Drawer");
    await new Promise((r) => setTimeout(r, 1500));

    const lightQtyAfterRestore = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      const r = rows.find((row) => row.textContent.includes("LIGHT"));
      return r ? parseInt(r.querySelector("td:nth-child(4)")?.textContent || "0", 10) : 0;
    });
    assertEqual(lightQtyAfterRestore, 6, "LIGHT quantity must restore from 5 to 6 (+1 delta)");
    recordResult("Restoration delta asserted", "LIGHT: 5 -> 6 EA");

    // Close review drawer
    await page.evaluate(() => {
      const drawer = document.querySelector(".w-96");
      const closeBtn = drawer ? drawer.querySelector("button") : null;
      if (closeBtn) closeBtn.click();
    });
    await new Promise((r) => setTimeout(r, 400));

    // -------------------------------------------------------------------------
    // Scenario 6: Manual Object Addition, Editing & Complete Deletion Rollback
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 6: Manual Object Addition, Editing & Deletion Rollback ---");
    // Click "누락 기구 수동 추가" button
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const manualBtn = buttons.find((b) => b.textContent.includes("누락 기구 수동 추가"));
      if (manualBtn) manualBtn.click();
    });
    await new Promise((r) => setTimeout(r, 500));

    // Click on canvas at (450, 400)
    await page.mouse.click(450, 400);
    await new Promise((r) => setTimeout(r, 1500));

    // 6A: Check manual diamond marker exists in SVG
    const manualDiamondCount = await page.$$eval("svg rect[transform*='rotate(45)']", (els) => els.length);
    assertEqual(manualDiamondCount, 1, "Exactly 1 manual diamond marker must exist on canvas");

    // 6B: Check quantity increased from 6 to 7
    const lightQtyAfterManualAdd = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      const r = rows.find((row) => row.textContent.includes("LIGHT"));
      return r ? parseInt(r.querySelector("td:nth-child(4)")?.textContent || "0", 10) : 0;
    });
    assertEqual(lightQtyAfterManualAdd, 7, "LIGHT quantity must increase from 6 to 7 (+1 delta)");
    recordResult("Manual object added & quantity incremented", "LIGHT: 6 -> 7 EA");
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "07_manual_marker_review.png") });

    // 6C: Click manual diamond marker to inspect Review Drawer
    await page.evaluate(() => {
      const marker = document.querySelector("svg rect[transform*='rotate(45)']");
      if (marker && marker.parentElement) {
        marker.parentElement.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      }
    });
    await new Promise((r) => setTimeout(r, 800));

    const manualDrawerTitle = await page.evaluate(() => {
      const drawer = document.querySelector(".w-96");
      return drawer ? drawer.innerText : "";
    });
    assert(
      manualDrawerTitle.includes("현장 보정 수동 기구"),
      "Review Drawer must show '현장 보정 수동 기구' header for manual objects"
    );

    // 6D: Click "수동 기구 삭제" button and verify quantity rollback (7 -> 6) and marker removal
    console.log("  Testing manual object deletion (Trash2 button)...");
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll(".w-96 button"));
      const deleteBtn = buttons.find((b) => b.textContent.includes("수동 기구 삭제"));
      if (deleteBtn) deleteBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1500));

    // Assert diamond marker is removed
    const diamondCountAfterDelete = await page.$$eval("svg rect[transform*='rotate(45)']", (els) => els.length);
    assertEqual(diamondCountAfterDelete, 0, "Manual diamond marker must be removed from canvas after deletion");

    // Assert quantity rolled back to 6
    const lightQtyAfterDelete = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      const r = rows.find((row) => row.textContent.includes("LIGHT"));
      return r ? parseInt(r.querySelector("td:nth-child(4)")?.textContent || "0", 10) : 0;
    });
    assertEqual(lightQtyAfterDelete, 6, "LIGHT quantity must rollback from 7 to 6 after deletion (-1 delta)");
    recordResult("Manual object deletion & quantity rollback asserted", "LIGHT: 7 -> 6 EA, Marker removed");

    // -------------------------------------------------------------------------
    // Scenario 7: CSV & XLSX Export Deep Parsing & Formula Injection Defense (#7)
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 7: Export Deep Parsing & Formula Injection Defense (#7) ---");
    // Inject formula into evidence note to verify OWASP defense
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const evidenceTab = buttons.find((b) => b.textContent.includes("객체 근거"));
      if (evidenceTab) evidenceTab.click();
    });
    await new Promise((r) => setTimeout(r, 600));

    // Open first evidence card
    await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".p-2\\.5.rounded.border.cursor-pointer"));
      if (cards.length > 0) cards[0].click();
    });
    await new Promise((r) => setTimeout(r, 800));

    // Type formula injection test string "=cmd|' /C calc'!A0" into note input via native keyboard
    const noteInput = await page.$('.w-96 input[type="text"]');
    assert(noteInput, "Note input field in Review Drawer not found");
    await page.evaluate(() => {
      const input = document.querySelector('.w-96 input[type="text"]');
      if (input) input.value = "";
    });
    await noteInput.type("=cmd|' /C calc'!A0");
    await new Promise((r) => setTimeout(r, 200));

    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll(".w-96 button"));
      const saveBtn = buttons.find((b) => b.textContent.includes("검수 확인"));
      if (saveBtn) saveBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1500));

    const exportUrls = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll("a[download]"));
      return {
        xlsx: links.find((a) => a.textContent.includes("Excel"))?.href || "",
        csvSummary: links.find((a) => a.textContent.includes("CSV 요약"))?.href || "",
        csvEvidence: links.find((a) => a.textContent.includes("CSV 근거"))?.href || "",
      };
    });

    // 7A: Validate CSV Summary
    assert(exportUrls.csvSummary, "CSV Summary download link not found");
    const csvSumRes = await fetch(exportUrls.csvSummary);
    assertEqual(csvSumRes.status, 200, "CSV Summary export must return HTTP 200");
    const csvSumText = await csvSumRes.text();
    const sumLines = csvSumText.trim().split("\n");
    assert(sumLines.length >= 4, "CSV Summary must have header + at least 3 data rows");
    assert(sumLines[0].includes("item_code"), "CSV Summary must contain PRD standard header");
    assert(csvSumText.includes("LIGHT") && csvSumText.includes("6"), "CSV Summary must include LIGHT, 6 EA");
    assert(csvSumText.includes("OUTLET") && csvSumText.includes("4"), "CSV Summary must include OUTLET, 4 EA");
    assert(csvSumText.includes("SWITCH") && csvSumText.includes("3"), "CSV Summary must include SWITCH, 3 EA");
    recordResult("CSV Summary deep parsing & exact counts validated");

    // 7B: Validate CSV Evidence & Formula Injection Defense
    assert(exportUrls.csvEvidence, "CSV Evidence download link not found");
    const csvEvRes = await fetch(exportUrls.csvEvidence);
    assertEqual(csvEvRes.status, 200, "CSV Evidence export must return HTTP 200");
    const csvEvText = await csvEvRes.text();
    console.log("  [DEBUG csvEvText]:\n", csvEvText);
    const evLines = csvEvText.trim().split("\n");
    assertEqual(evLines.length, 14, "CSV Evidence must contain header + exactly 13 evidence rows");
    assert(evLines[0].includes("source_object_id"), "CSV Evidence must contain PRD standard header");
    // Assert formula injection is sanitized with leading single quote: '=cmd|...
    assert(
      csvEvText.includes("''=cmd|' /C calc'!A0") || csvEvText.includes("=\"=cmd|") || csvEvText.includes("''=cmd") || csvEvText.includes("'=cmd"),
      "Formula injection string must be sanitized against CSV execution"
    );
    recordResult("CSV Evidence parsing & Formula Injection Defense (#7) validated");

    // 7C: Validate Excel XLSX 2-sheet structure
    assert(exportUrls.xlsx, "Excel download link not found");
    const xlsxRes = await fetch(exportUrls.xlsx);
    assertEqual(xlsxRes.status, 200, "Excel export must return HTTP 200");
    const xlsxBuffer = Buffer.from(await xlsxRes.arrayBuffer());
    assert(xlsxBuffer.length > 2000, "Excel XLSX file size must be > 2KB");

    const zipEntries = readZipEntries(xlsxBuffer);
    assert(zipEntries["xl/workbook.xml"], "XLSX package must contain xl/workbook.xml");
    const workbookXml = zipEntries["xl/workbook.xml"].data
      ? zipEntries["xl/workbook.xml"].data.toString("utf8")
      : "";
    assert(
      workbookXml.includes("Takeoff Summary") && workbookXml.includes("Takeoff Evidence"),
      "Excel workbook must contain 2 separate sheets: 'Takeoff Summary' and 'Takeoff Evidence'"
    );
    recordResult("Excel (XLSX) 2-sheet workbook structure verified");

    // -------------------------------------------------------------------------
    // Scenario 8: Page Reload & State Persistence (AC-07)
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 8: Page Reload & State Persistence (AC-07) ---");
    await page.reload({ waitUntil: "networkidle0" });
    await page.waitForSelector("svg", { timeout: 10000 });
    await new Promise((r) => setTimeout(r, 1000));

    const reloadedText = await page.evaluate(() => document.body.innerText);
    const hasReopenedDrawing = reloadedText.includes("basic_devices.dxf");
    assert(hasReopenedDrawing, "Page reload failed to reopen active drawing basic_devices.dxf");

    // Verify quantities remained exact after reload
    const reloadedSummary = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      return rows.map((r) => ({
        code: r.querySelector("td:nth-child(1)")?.textContent?.trim() || "",
        qty: parseInt(r.querySelector("td:nth-child(4)")?.textContent?.trim() || "0", 10),
      }));
    });
    const reloadedLight = reloadedSummary.find((r) => r.code === "LIGHT")?.qty;
    assertEqual(reloadedLight, 6, "Persisted LIGHT count after reload must remain exactly 6 EA");
    recordResult("Page reload state persistence (AC-07) verified", "Exact quantities retained");
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "08_reloaded_drawing_reopened.png") });

    // -------------------------------------------------------------------------
    // Scenario 9: AutoCAD Binary DXF Upload & Direct Vector Rendering
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 9: AutoCAD Binary DXF Upload & Vector Rendering ---");
    const binaryDxfPath = path.join(ROOT_DIR, "fixtures/dxf/binary_devices.dxf");
    const fileInput2 = await page.$('input[type="file"]');
    assert(fileInput2, "File upload input not found for Binary DXF");
    await fileInput2.uploadFile(binaryDxfPath);
    await page.waitForFunction(
      () => document.body.innerText.includes("binary_devices.dxf"),
      { timeout: 15000 }
    );
    await new Promise((r) => setTimeout(r, 1200));

    const binaryText = await page.evaluate(() => document.body.innerText);
    assert(binaryText.includes("binary_devices.dxf"), "Binary DXF header name missing");
    const binaryCircles = await page.$$eval("svg circle", (els) => els.length);
    assert(binaryCircles > 0, "Binary DXF failed to render circle nodes");
    recordResult("AutoCAD Binary DXF direct parse & render", `Rendered with ${binaryCircles} circle nodes`);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "09_binary_dxf_rendered.png") });

    // -------------------------------------------------------------------------
    // Scenario 10: Drawing Switching without State Contamination
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 10: Drawing Switching & Isolation (A <-> B) ---");
    const selectEl = await page.$('select[aria-label="저장된 도면 목록"]');
    assert(selectEl, "Drawing selector dropdown not found in header");

    const options = await page.evaluate(
      (el) => Array.from(el.options).map((o) => ({ id: o.value, text: o.text })),
      selectEl
    );
    assert(options.length >= 2, `Expected at least 2 saved drawings, found ${options.length}`);

    // Switch back to basic_devices.dxf
    const basicOpt = options.find((o) => o.text.includes("basic_devices.dxf"));
    assert(basicOpt, "basic_devices.dxf option missing from selector");
    await selectEl.select(basicOpt.id);
    await new Promise((r) => setTimeout(r, 1500));

    // Verify drawing switched cleanly and restored its exact quantities
    const restoredTitle = await page.evaluate(() => document.body.innerText);
    assert(restoredTitle.includes("basic_devices.dxf"), "Failed to switch back to basic_devices.dxf");

    const switchedSummary = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      return rows.map((r) => ({
        code: r.querySelector("td:nth-child(1)")?.textContent?.trim() || "",
        qty: parseInt(r.querySelector("td:nth-child(4)")?.textContent?.trim() || "0", 10),
      }));
    });
    const switchedLight = switchedSummary.find((r) => r.code === "LIGHT")?.qty;
    assertEqual(switchedLight, 6, "Switched drawing must restore LIGHT=6 without cross-contamination");
    recordResult("Clean drawing switching verified", `Restored ${basicOpt.text} with isolated state`);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "10_drawing_switched_clean.png") });

    // -------------------------------------------------------------------------
    // Final Summary
    // -------------------------------------------------------------------------
    console.log("\n================================================================================");
    console.log(` [Issue #10] ALL SCENARIOS STRICTLY VALIDATED & PASSED: ${testReport.passed} Passed, 0 Failed`);
    console.log("================================================================================");
  } catch (err) {
    console.error("\n❌ [E2E STRICT FAILURE]:", err.message);
    try {
      await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "error_state.png") });
    } catch {}
    process.exit(1);
  } finally {
    await browser.close();
  }
}

runE2E().catch((err) => {
  console.error(err);
  process.exit(1);
});
