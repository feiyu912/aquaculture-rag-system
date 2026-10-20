import { chromium } from "@playwright/test";
import fs from "node:fs";

/**
 * Drives the real UI (no mocks) to produce the final acceptance screenshots:
 * ask a real question, wait for the real LLM answer, open the citation panel,
 * follow a real citation into the PDF reader (with the real bbox), and load
 * the matching debug trace.
 */

const BASE = process.env.AQUA_WEB_BASE ?? "http://127.0.0.1:3000";
const QUESTION =
  process.env.QUESTION ??
  "中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？请给出具体数值。";

const viewports = [
  { name: "1440", width: 1440, height: 900, isMobile: false },
  { name: "390", width: 390, height: 844, isMobile: true },
];

fs.mkdirSync(".review", { recursive: true });
const browser = await chromium.launch();

for (const vp of viewports) {
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    hasTouch: vp.isMobile,
    isMobile: vp.isMobile,
  });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));

  const shot = async (name) => {
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    await page.screenshot({ path: `.review/FINAL-${name}-${vp.name}.png` });
    console.log(
      `  ${name}-${vp.name}: overflow=${overflow}px errors=${errors.length}` +
        (errors.length ? ` :: ${errors[0].slice(0, 100)}` : ""),
    );
  };

  // ---- 1. chat: ask a real question, wait for the real answer -------------
  console.log(`[${vp.name}] chat…`);
  await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
  const input = page.getByPlaceholder(/提出一个水产养殖问题/);
  await input.waitFor({ timeout: 30_000 });
  await input.fill(QUESTION);
  await input.press("Enter");
  try {
    await page.getByText(/总计 \d/).waitFor({ timeout: 180_000 });
  } catch {
    console.log(`  !! answer did not complete for ${vp.name}`);
  }
  await page.waitForTimeout(1200);
  await shot("chat");

  // ---- 2. citation panel ---------------------------------------------------
  const panelBtn = page.getByRole("button", { name: "引用来源面板" });
  if (await panelBtn.count()) {
    await panelBtn.first().click();
    await page.waitForTimeout(900);
    await shot("chat-sources");
    await panelBtn.first().click();
    await page.waitForTimeout(400);
  }

  // ---- 3. debug trace for this very answer --------------------------------
  const debugLink = page.locator('a[href*="/debug?request_id="]').first();
  let requestId = "";
  if (await debugLink.count()) {
    requestId = new URL(await debugLink.getAttribute("href"), BASE).searchParams.get(
      "request_id",
    );
  }
  if (requestId) {
    await page.goto(`${BASE}/debug?request_id=${requestId}`, {
      waitUntil: "networkidle",
    });
    await page.waitForTimeout(2500);
    await shot("debug");
    // Scroll the anchoring card into view.
    const card = page.getByText("按来源锚定检索").first();
    if (await card.count()) {
      await card.scrollIntoViewIfNeeded();
      await page.waitForTimeout(700);
      await shot("debug-anchor");
    }
  } else {
    console.log(`  !! no request_id link found for ${vp.name}`);
  }

  // ---- 4. reader: follow a real citation into the PDF ----------------------
  await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
  const chip = page.locator("button", { hasText: /^S?\d+$/ }).first();
  if (await chip.count()) {
    await chip.click();
    await page.waitForURL(/\/reader\?/, { timeout: 30_000 });
    await page.waitForTimeout(6000);
    await shot("reader");
  } else {
    console.log(`  !! no citation chip for ${vp.name}`);
  }

  // ---- 5. knowledge --------------------------------------------------------
  await page.goto(`${BASE}/knowledge`, { waitUntil: "networkidle" });
  await page.waitForTimeout(2000);
  await shot("knowledge");

  await context.close();
}

await browser.close();
