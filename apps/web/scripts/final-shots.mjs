import { chromium } from "@playwright/test";
import fs from "node:fs";

const BASE = process.env.AQUA_WEB_BASE ?? "http://127.0.0.1:3000";
const DOC = process.env.DOC_ID ?? "4bf20f9d-e491-4c8d-8ead-088e388d83ee";
const REQ = process.env.REQ_ID ?? "";

const pages = [
  { name: "chat", path: "/chat", wait: 2500 },
  { name: "knowledge", path: "/knowledge", wait: 2500 },
  { name: "reader", path: `/reader?document_id=${DOC}`, wait: 6000 },
  { name: "debug", path: REQ ? `/debug?request_id=${REQ}` : "/debug", wait: 3500 },
];

const viewports = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
];

fs.mkdirSync(".review", { recursive: true });
const browser = await chromium.launch();

for (const vp of viewports) {
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: 1,
    locale: "zh-CN",
  });
  for (const p of pages) {
    const page = await context.newPage();
    const errors = [];
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(BASE + p.path, { waitUntil: "networkidle" }).catch(() => {});
    await page.waitForTimeout(p.wait);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    await page.screenshot({
      path: `.review/FINAL-${p.name}-${vp.name}.png`,
      fullPage: false,
    });
    console.log(
      `${p.name}-${vp.name}: overflow=${overflow}px errors=${errors.length}` +
        (errors.length ? ` :: ${errors[0].slice(0, 120)}` : ""),
    );
    await page.close();
  }
  await context.close();
}

await browser.close();
