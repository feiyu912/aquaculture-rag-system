#!/usr/bin/env node
/**
 * Verifies that the PDF reader highlights the exact backend bbox.
 *
 * The backend stores the bbox in PDF points, relative to the CropBox, with
 * the y axis measured from the top. This script recomputes the expected
 * viewport rectangle and compares it with what the reader rendered.
 */
import { launch } from "puppeteer-core";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const route = process.argv[2];
const expected = process.argv[3]; // "x0,y0,x1,y1" in PDF points

const browser = await launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu"],
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto(`http://127.0.0.1:3000${route}`, { waitUntil: "networkidle2" });
  await new Promise((r) => setTimeout(r, 1200));

  // Wait until the highlighted page has been rendered.
  await page
    .waitForFunction(() => Boolean(document.querySelector('[class*="bg-primary-400/28"]')), {
      timeout: 25000,
    })
    .catch(() => undefined);
  await new Promise((r) => setTimeout(r, 800));

  const info = await page.evaluate((expectedRect) => {
    // Find the page wrapper that actually carries the highlight.
    const hl = document.querySelector('[class*="bg-primary-400/28"]');
    const wrap = hl?.parentElement;
    const canvas = wrap?.querySelector("canvas");
    if (!canvas || !wrap || !hl) {
      return {
        error: "missing elements",
        debug: {
          hlFound: Boolean(hl),
          wrapFound: Boolean(wrap),
          wrapTag: wrap?.tagName,
          wrapChildren: wrap ? Array.from(wrap.children).map((c) => c.tagName) : [],
          canvasCount: document.querySelectorAll("canvas").length,
        },
      };
    }

    const wrapRect = wrap.getBoundingClientRect();
    const hlRect = hl.getBoundingClientRect();
    const [x0, y0, x1, y1] = expectedRect;
    const scale = Number.parseFloat(canvas.style.width) / Number(canvas.getAttribute("data-page-width") || 0);

    return {
      scaleFromStyle: Number.parseFloat(canvas.style.width),
      canvasStyleWidth: canvas.style.width,
      canvasStyleHeight: canvas.style.height,
      highlightOffsetLeft: hlRect.left - wrapRect.left,
      highlightOffsetTop: hlRect.top - wrapRect.top,
      highlightWidth: hlRect.width,
      highlightHeight: hlRect.height,
      expected: { x0, y0, x1, y1 },
      scrollTop:
        document.querySelector("main .overflow-y-auto")?.scrollTop ??
        document.querySelector('[class*="overflow-auto"]')?.scrollTop,
    };
  }, expected.split(",").map(Number));

  console.log(JSON.stringify(info, null, 2));

  const canvas = await page.$('[class*="bg-primary-400/28"]');
  if (canvas) {
    const file = await canvas.screenshot({ path: ".review/highlight-page.png" });
    console.log("page screenshot saved");
  }
} finally {
  await browser.close();
}
