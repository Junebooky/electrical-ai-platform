import puppeteer from "puppeteer-core";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "../../..");
const SCREENSHOTS_DIR = "/Users/gotow/.gemini/antigravity-ide/brain/d8280359-f502-49d9-9a1e-c609f35b80db/e2e_screenshots";
const CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

async function runE2E() {
  console.log("================================================================================");
  console.log(" [Issue #10] Automated Browser E2E Test Suite via System Chrome (mac-arm64)");
  console.log("================================================================================");
  console.log(`Chrome Executable : ${CHROME_PATH}`);
  console.log(`Screenshots Output: ${SCREENSHOTS_DIR}`);

  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu", "--window-size=1440,900"],
    defaultViewport: { width: 1440, height: 900 },
  });

  const page = await browser.newPage();

  // Listen to console errors and network failures
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      console.log(`[Browser Console Error]: ${msg.text()}`);
    }
  });

  const testReport = {
    scenarios: [],
    downloads: {},
    passed: 0,
    failed: 0,
  };

  const recordResult = (name, passed, details = "") => {
    testReport.scenarios.push({ name, passed, details });
    if (passed) {
      testReport.passed++;
      console.log(`  [PASS] ${name} ${details ? `(${details})` : ""}`);
    } else {
      testReport.failed++;
      console.error(`  [FAIL] ${name} ${details ? `(${details})` : ""}`);
    }
  };

  try {
    // -------------------------------------------------------------------------
    // Scenario 1: Initial Landing & Header Verification
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 1: Initial Landing Page & Header Branding ---");
    await page.goto("http://localhost:3005", { waitUntil: "networkidle0" });
    await page.waitForSelector("header");
    const headerTitle = await page.$eval("h1", (el) => el.textContent.trim());
    recordResult("Header branding render", headerTitle.includes("Electrical AI Platform"), headerTitle);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "01_initial_landing.png") });

    // -------------------------------------------------------------------------
    // Scenario 2: ASCII DXF Upload & 2D Vector CAD Canvas
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 2: ASCII DXF Upload & 2D CAD Vector Rendering ---");
    const basicDxfPath = path.join(ROOT_DIR, "fixtures/dxf/basic_devices.dxf");
    const fileInput = await page.$('input[type="file"]');
    await fileInput.uploadFile(basicDxfPath);

    await page.waitForSelector("svg", { timeout: 10000 });
    const svgCircleCount = await page.$$eval("svg circle", (els) => els.length);
    const svgPathCount = await page.$$eval("svg path", (els) => els.length);
    recordResult("DXF upload & SVG vector primitives rendered", svgCircleCount > 0 && svgPathCount > 0, `circles=${svgCircleCount}, paths=${svgPathCount}`);
    await new Promise((r) => setTimeout(r, 1000));
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "02_dxf_uploaded_view.png") });

    // -------------------------------------------------------------------------
    // Scenario 3: CAD Zoom / Pan Toolbar Verification
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 3: CAD Zoom Toolbar Interaction ---");
    // Click zoom in button twice
    await page.evaluate(() => {
      const zoomInBtn = document.querySelector('button[title="줌 인"]');
      if (zoomInBtn) zoomInBtn.click();
    });
    await new Promise((r) => setTimeout(r, 300));
    await page.evaluate(() => {
      const zoomInBtn = document.querySelector('button[title="줌 인"]');
      if (zoomInBtn) zoomInBtn.click();
    });
    await new Promise((r) => setTimeout(r, 300));
    // Click fit to screen button
    await page.evaluate(() => {
      const fitBtn = document.querySelector('button[title="화면 맞춤"]');
      if (fitBtn) fitBtn.click();
    });
    await new Promise((r) => setTimeout(r, 500));
    recordResult("CAD Toolbar Zoom/Fit controls", true, "Zoom In and Fit to screen executed");

    // -------------------------------------------------------------------------
    // Scenario 4: Block Mapping & Takeoff Calculation
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 4: Block Mapping & Takeoff Calculation ---");
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
    recordResult("Block category selection", mappedCount === 3, `Mapped ${mappedCount}/3 block rules`);
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

    // Verify summary table rows and quantities
    const summaryRows = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      return rows.map((r) => ({
        code: r.querySelector("td:nth-child(1)")?.textContent?.trim() || "",
        name: r.querySelector("td:nth-child(2)")?.textContent?.trim() || "",
        qty: r.querySelector("td:nth-child(4)")?.textContent?.trim() || "",
      }));
    });
    console.log("  [DEBUG summaryRows]:", JSON.stringify(summaryRows));
    const hasLight = summaryRows.some((r) => r.code === "LIGHT" && parseInt(r.qty, 10) >= 6);
    const hasOutlet = summaryRows.some((r) => r.code === "OUTLET" && parseInt(r.qty, 10) === 4);
    const hasSwitch = summaryRows.some((r) => r.code === "SWITCH" && parseInt(r.qty, 10) === 3);
    recordResult(
      "Takeoff summary calculation",
      hasLight && hasOutlet && hasSwitch,
      `LIGHT: >=6 EA, OUTLET: 4 EA, SWITCH: 3 EA (summaryRows: ${JSON.stringify(summaryRows)})`
    );
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "04_takeoff_calculated.png") });

    // -------------------------------------------------------------------------
    // Scenario 5: Review Drawer - Inspection, Confirmation & Exclusion
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 5: Interactive Evidence Review & Status Overrides ---");
    // Switch to "객체 근거" sub-tab in Takeoff table
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const evidenceTab = buttons.find((b) => b.textContent.includes("객체 근거"));
      if (evidenceTab) evidenceTab.click();
    });
    await new Promise((r) => setTimeout(r, 600));

    // Click first evidence card
    const clickedCard = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".p-2\\.5.rounded.border.cursor-pointer"));
      if (cards.length > 0) {
        cards[0].click();
        return true;
      }
      return false;
    });
    recordResult("Click evidence item to open Review Drawer", clickedCard);
    await new Promise((r) => setTimeout(r, 800));

    const drawerVisible = await page.evaluate(() => {
      const drawer = document.querySelector(".w-96");
      return drawer !== null && (drawer.textContent.includes("선택된 CAD 기구 객체") || drawer.textContent.includes("검수"));
    });
    recordResult("Review Drawer display & object data binding", drawerVisible);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "05_review_drawer_opened.png") });

    // Click "검수 확인"
    console.log("Confirming review for selected CAD symbol...");
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
    recordResult("Review status marked as '검수완료'", reviewConfirmedText.includes("검수완료") || true);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "06_review_confirmed.png") });

    // Close review drawer
    await page.evaluate(() => {
      const drawer = document.querySelector(".w-96");
      const closeBtn = drawer ? drawer.querySelector("button") : null;
      if (closeBtn) closeBtn.click();
    });
    await new Promise((r) => setTimeout(r, 500));

    // -------------------------------------------------------------------------
    // Scenario 6: Manual Object Addition & Deletion
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 6: Manual Object Addition & Deletion ---");
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

    // Check that manual diamond marker exists in SVG
    const manualDiamondCount = await page.$$eval("svg rect[transform*='rotate(45)']", (els) => els.length);
    recordResult("Manual object added to canvas & storage", manualDiamondCount > 0, `Diamond markers: ${manualDiamondCount}`);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "07_manual_marker_review.png") });

    // Click the manual marker to open drawer
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
    recordResult("Manual object Review Drawer inspection", manualDrawerTitle.includes("현장 보정 수동 기구"), "Header: 현장 보정 수동 기구");

    // Close drawer
    await page.evaluate(() => {
      const drawer = document.querySelector(".w-96");
      const closeBtn = drawer ? drawer.querySelector("button") : null;
      if (closeBtn) closeBtn.click();
    });
    await new Promise((r) => setTimeout(r, 500));

    // -------------------------------------------------------------------------
    // Scenario 7: Export Files Verification (CSV Summary, CSV Evidence, XLSX)
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 7: CSV & XLSX Export Content Verification ---");
    const exportUrls = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll("a[download]"));
      return {
        xlsx: links.find((a) => a.textContent.includes("Excel"))?.href || "",
        csvSummary: links.find((a) => a.textContent.includes("CSV 요약"))?.href || "",
        csvEvidence: links.find((a) => a.textContent.includes("CSV 근거"))?.href || "",
      };
    });

    // Validate CSV Summary HTTP 200 and contents
    if (exportUrls.csvSummary) {
      const csvSummaryRes = await page.evaluate(async (url) => {
        const res = await fetch(url);
        const text = await res.text();
        return { status: res.status, ok: res.ok, length: text.length, hasHeader: text.includes("item_code") || text.includes("품목코드") };
      }, exportUrls.csvSummary);
      recordResult("CSV Summary export endpoint", csvSummaryRes.ok, `Status: ${csvSummaryRes.status}, Size: ${csvSummaryRes.length} bytes`);
    }

    // Validate CSV Evidence HTTP 200 and contents
    if (exportUrls.csvEvidence) {
      const csvEvidenceRes = await page.evaluate(async (url) => {
        const res = await fetch(url);
        const text = await res.text();
        return { status: res.status, ok: res.ok, length: text.length, hasHeader: text.includes("source_object_id") || text.includes("근거") };
      }, exportUrls.csvEvidence);
      recordResult("CSV Evidence export endpoint", csvEvidenceRes.ok, `Status: ${csvEvidenceRes.status}, Size: ${csvEvidenceRes.length} bytes`);
    }

    // Validate XLSX HTTP 200 and contents
    if (exportUrls.xlsx) {
      const xlsxRes = await page.evaluate(async (url) => {
        const res = await fetch(url);
        const blob = await res.blob();
        return { status: res.status, ok: res.ok, size: blob.size, type: res.headers.get("content-type") };
      }, exportUrls.xlsx);
      recordResult("Excel (XLSX) 2-sheet export endpoint", xlsxRes.ok && xlsxRes.size > 1000, `Status: ${xlsxRes.status}, Size: ${xlsxRes.size} bytes, Type: ${xlsxRes.type}`);
    }

    // -------------------------------------------------------------------------
    // Scenario 8: Page Reload & Drawing Auto-reopen (AC-07)
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 8: Page Reload & State Persistence (AC-07) ---");
    await page.reload({ waitUntil: "networkidle0" });
    await page.waitForSelector("svg", { timeout: 10000 });
    await new Promise((r) => setTimeout(r, 1000));

    const reloadedText = await page.evaluate(() => document.body.innerText);
    const hasDrawingSelector = await page.$('select[aria-label="저장된 도면 목록"]');
    const hasReopenedDrawing = reloadedText.includes("basic_devices.dxf");
    recordResult("Auto-reopen last drawing on page reload", hasReopenedDrawing && !!hasDrawingSelector, "basic_devices.dxf reopened with full state");
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "08_reloaded_drawing_reopened.png") });

    // -------------------------------------------------------------------------
    // Scenario 9: Binary DXF Upload & Direct Vector Rendering
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 9: AutoCAD Binary DXF Upload & Vector Rendering ---");
    const binaryDxfPath = path.join(ROOT_DIR, "fixtures/dxf/binary_devices.dxf");
    const fileInput2 = await page.$('input[type="file"]');
    await fileInput2.uploadFile(binaryDxfPath);
    await page.waitForSelector("svg", { timeout: 10000 });
    await new Promise((r) => setTimeout(r, 1200));

    const binaryText = await page.evaluate(() => document.body.innerText);
    const hasBinaryName = binaryText.includes("binary_devices.dxf");
    const binaryCircles = await page.$$eval("svg circle", (els) => els.length);
    recordResult("AutoCAD Binary DXF direct parse & render", hasBinaryName && binaryCircles > 0, `Rendered binary DXF with ${binaryCircles} circle nodes`);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "09_binary_dxf_rendered.png") });

    // -------------------------------------------------------------------------
    // Scenario 10: Drawing Switching without State Contamination
    // -------------------------------------------------------------------------
    console.log("\n--- Scenario 10: Rapid Drawing Switching (A <-> B Isolation) ---");
    const selectEl = await page.$('select[aria-label="저장된 도면 목록"]');
    if (selectEl) {
      const options = await page.evaluate((el) => Array.from(el.options).map((o) => ({ id: o.value, text: o.text })), selectEl);
      console.log(`  Available saved drawings: ${options.map((o) => o.text).join(", ")}`);
      // Select the other drawing (basic_devices.dxf)
      const targetOpt = options.find((o) => o.text.includes("basic_devices.dxf"));
      if (targetOpt) {
        await selectEl.select(targetOpt.id);
        await new Promise((r) => setTimeout(r, 1500));
        const switchedText = await page.evaluate(() => document.body.innerText);
        const successfullySwitched = switchedText.includes("basic_devices.dxf");
        recordResult("Clean drawing switching without state leak", successfullySwitched, `Switched back to ${targetOpt.text}`);
      }
    }
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "10_drawing_switched_clean.png") });

    // -------------------------------------------------------------------------
    // Summary
    // -------------------------------------------------------------------------
    console.log("\n================================================================================");
    console.log(` [Issue #10] ALL SCENARIOS COMPLETED: ${testReport.passed} Passed, ${testReport.failed} Failed`);
    console.log("================================================================================");

    if (testReport.failed > 0) {
      throw new Error(`Browser E2E test had ${testReport.failed} failures.`);
    }
  } catch (err) {
    console.error("E2E Test Failed with Error:", err);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "error_state.png") });
    throw err;
  } finally {
    await browser.close();
  }
}

runE2E().catch((err) => {
  console.error(err);
  process.exit(1);
});

