#!/usr/bin/env node
/**
 * Visual review harness.
 *
 * Usage:
 *   node scripts/review.mjs <route> [--w 1440] [--h 900] [--out name]
 *                           [--dark] [--full] [--audit]
 *
 * Renders a route with the real backend connected, captures a screenshot and
 * (with --audit) reports horizontal overflow offenders plus console errors.
 * The audit step is what turns "looks fine" into a measured check.
 */
import { launch } from "puppeteer-core";
import { mkdirSync } from "node:fs";
import path from "node:path";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BASE = process.env.AQUA_WEB_BASE ?? "http://127.0.0.1:3000";
const OUT_DIR = path.resolve(process.cwd(), ".review");

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1) return fallback;
  const value = process.argv[index + 1];
  return value && !value.startsWith("--") ? value : true;
}

const route = process.argv[2]?.startsWith("/") ? process.argv[2] : "/chat";
const width = Number(arg("w", 1440));
const height = Number(arg("h", 900));
const name = String(arg("out", "shot"));
const dark = Boolean(arg("dark", false));
const full = Boolean(arg("full", false));
const audit = Boolean(arg("audit", true));
const scrollTo = Number(arg("scroll", 0));

mkdirSync(OUT_DIR, { recursive: true });

const browser = await launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 2 });
  await page.emulateMediaFeatures([
    { name: "prefers-color-scheme", value: dark ? "dark" : "light" },
  ]);

  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));

  await page.goto(`${BASE}${route}`, { waitUntil: "networkidle2", timeout: 45_000 });
  if (dark) {
    await page.evaluate(() => {
      window.localStorage.setItem("aqua-rag-theme", "dark");
    });
    await page.reload({ waitUntil: "networkidle2", timeout: 45_000 });
  }
  await new Promise((resolve) => setTimeout(resolve, 1200));

  if (scrollTo) {
    await page.evaluate((y) => {
      const scroller =
        document.querySelector("main .overflow-y-auto") ??
        document.querySelector("main") ??
        document.scrollingElement;
      if (scroller) scroller.scrollTop = y;
      window.scrollTo(0, y);
    }, scrollTo);
    await new Promise((resolve) => setTimeout(resolve, 700));
  }

  const metrics = await page.evaluate(() => {
    const doc = document.documentElement;
    const offenders = [];
    const viewportWidth = doc.clientWidth;
    for (const node of document.querySelectorAll("body *")) {
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      if (rect.right > viewportWidth + 1 || rect.left < -1) {
        const style = getComputedStyle(node);
        if (style.position === "fixed") continue;
        offenders.push({
          tag: node.tagName.toLowerCase(),
          cls: (node.className?.toString?.() ?? "").slice(0, 110),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
        });
      }
    }
    return {
      scrollWidth: doc.scrollWidth,
      clientWidth: viewportWidth,
      bodyScrollWidth: document.body.scrollWidth,
      offenders: offenders.slice(0, 12),
    };
  });

  const file = path.join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: full });

  console.log(
    JSON.stringify(
      {
        route,
        viewport: `${width}x${height}`,
        dark,
        file,
        overflow:
          metrics.scrollWidth > metrics.clientWidth
            ? {
                scrollWidth: metrics.scrollWidth,
                clientWidth: metrics.clientWidth,
                offenders: metrics.offenders,
              }
            : null,
        consoleErrors: errors.slice(0, 8),
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
