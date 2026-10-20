import { expect, test, type Page } from "@playwright/test";

import { API_BASE } from "./helpers";

/** A real document from the knowledge base with a verified citation bbox. */
const DOC_ID = "3f534c05-99c9-493e-9e18-323f9ee9a3c1";
const VERSION_ID = "2b5511ca-7886-4e40-964e-5a069da06694";

interface Location {
  page: number;
  bbox: [number, number, number, number];
  page_width: number;
  page_height: number;
  rotation: number;
}

/** Pull a citation location for the document straight from the API. */
async function fetchCitationLocation(page: Page, pageNumber: number): Promise<Location> {
  const response = await page.request.get(`${API_BASE}/api/documents/${DOC_ID}/citations`);
  expect(response.ok()).toBeTruthy();
  const citations = (await response.json()) as { page: number | null; bbox: Location | null }[];
  const match = citations.find((citation) => citation.page === pageNumber && citation.bbox);
  expect(match, `a citation on page ${pageNumber} should exist`).toBeTruthy();
  return match!.bbox!;
}

test.describe("PDF 文献阅读器", () => {
  test("渲染 PDF 并可翻页", async ({ page }) => {
    await page.goto(`/reader?document_id=${DOC_ID}&version_id=${VERSION_ID}`);
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByLabel(/第 \d+ 页，共 \d+ 页/)).toBeVisible();
  });

  test("点击左侧页码列表会把画布滚动到该页", async ({ page }) => {
    await page.goto(`/reader?document_id=${DOC_ID}&version_id=${VERSION_ID}`);
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 60_000 });

    const before = await page.evaluate(() => {
      const scroller = document.querySelector("main .overflow-auto, main .overflow-y-auto");
      return scroller?.scrollTop ?? 0;
    });

    // Click page 8 in the context panel.
    await page.locator('[data-page="8"]').first().click();
    await page.waitForTimeout(1200);

    const after = await page.evaluate(() => {
      const scroller = document.querySelector("main .overflow-auto, main .overflow-y-auto");
      const target = document.querySelector('[data-pdf-page="8"]');
      const scrollerRect = scroller?.getBoundingClientRect();
      const targetRect = target?.getBoundingClientRect();
      return {
        scrollTop: scroller?.scrollTop ?? 0,
        targetOffsetFromTop:
          scrollerRect && targetRect ? targetRect.top - scrollerRect.top : null,
      };
    });

    expect(after.scrollTop).toBeGreaterThan(before);
    // The requested page should now sit near the top of the viewport.
    expect(after.targetOffsetFromTop).not.toBeNull();
    expect(Math.abs(after.targetOffsetFromTop!)).toBeLessThan(120);
  });

  test("引用高亮落在被引用的原文区域（几何 + 像素双重校验）", async ({ page }) => {
    const location = await fetchCitationLocation(page, 7);

    await page.goto(
      `/reader?document_id=${DOC_ID}&version_id=${VERSION_ID}&page=${location.page}&bbox=${location.bbox.join(",")}`,
    );
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 60_000 });

    const highlight = page.locator("div.bg-primary-400\\/28").first();
    await expect(highlight).toBeVisible({ timeout: 60_000 });

    const measured = await page.evaluate(() => {
      const hl = document.querySelector("div.bg-primary-400\\/28") as HTMLElement | null;
      const wrap = hl?.parentElement;
      const canvas = wrap?.querySelector("canvas") as HTMLCanvasElement | null;
      if (!hl || !wrap || !canvas) return null;
      const wrapRect = wrap.getBoundingClientRect();
      const hlRect = hl.getBoundingClientRect();
      return {
        left: hlRect.left - wrapRect.left,
        top: hlRect.top - wrapRect.top,
        width: hlRect.width,
        height: hlRect.height,
        canvasWidth: parseFloat(canvas.style.width),
        canvasHeight: parseFloat(canvas.style.height),
        devicePixelRatio: window.devicePixelRatio,
      };
    });

    expect(measured).not.toBeNull();
    const m = measured!;

    // The transform must hold at whatever zoom level is active.
    const scale = m.canvasWidth / location.page_width;
    expect(Math.abs(m.left - location.bbox[0] * scale)).toBeLessThan(1.5);
    expect(Math.abs(m.top - (location.page_height - location.bbox[3]) * scale)).toBeLessThan(1.5);
    expect(Math.abs(m.width - (location.bbox[2] - location.bbox[0]) * scale)).toBeLessThan(1.5);
    expect(Math.abs(m.height - (location.bbox[3] - location.bbox[1]) * scale)).toBeLessThan(1.5);

    // The highlight must actually cover ink: sample the canvas under it.
    const ink = await page.evaluate(() => {
      const hl = document.querySelector("div.bg-primary-400\\/28") as HTMLElement | null;
      const canvas = hl?.parentElement?.querySelector("canvas") as HTMLCanvasElement | null;
      if (!hl || !canvas) return null;
      const wrapRect = hl.parentElement!.getBoundingClientRect();
      const hlRect = hl.getBoundingClientRect();
      const ratio = canvas.width / wrapRect.width;
      const x = Math.round((hlRect.left - wrapRect.left) * ratio);
      const y = Math.round((hlRect.top - wrapRect.top) * ratio);
      const w = Math.max(1, Math.round(hlRect.width * ratio));
      const h = Math.max(1, Math.round(hlRect.height * ratio));
      const ctx = canvas.getContext("2d")!;
      const data = ctx.getImageData(x, y, w, h).data;
      let dark = 0;
      let total = 0;
      for (let i = 0; i < data.length; i += 4) {
        total += 1;
        if (data[i] < 200 || data[i + 1] < 200 || data[i + 2] < 200) dark += 1;
      }
      return { dark, total, ratio: dark / Math.max(1, total) };
    });

    expect(ink).not.toBeNull();
    // Text glyphs should cover a meaningful part of the highlighted region.
    expect(ink!.ratio).toBeGreaterThan(0.01);
  });

  test("缩放时高亮与页面同步缩放", async ({ page }) => {
    const location = await fetchCitationLocation(page, 7);
    await page.goto(
      `/reader?document_id=${DOC_ID}&version_id=${VERSION_ID}&page=${location.page}&bbox=${location.bbox.join(",")}`,
    );
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
    // The highlight only exists once the page has been rendered.
    await expect(page.locator("div.bg-primary-400\\/28").first()).toBeVisible({ timeout: 60_000 });

    const read = async () =>
      page.evaluate(() => {
        const hl = document.querySelector("div.bg-primary-400\\/28") as HTMLElement | null;
        const wrap = hl?.parentElement;
        const canvas = wrap?.querySelector("canvas") as HTMLCanvasElement | null;
        if (!hl || !wrap || !canvas) return null;
        const wrapRect = wrap.getBoundingClientRect();
        const hlRect = hl.getBoundingClientRect();
        return {
          left: hlRect.left - wrapRect.left,
          top: hlRect.top - wrapRect.top,
          width: hlRect.width,
          height: hlRect.height,
          canvasWidth: parseFloat(canvas.style.width),
        };
      });

    const before = await read();
    expect(before).not.toBeNull();

    await page.getByRole("button", { name: "放大" }).click();
    await page.getByRole("button", { name: "放大" }).click();
    await page.waitForTimeout(1500);

    const after = await read();
    expect(after).not.toBeNull();

    const zoomRatio = after!.canvasWidth / before!.canvasWidth;
    expect(zoomRatio).toBeGreaterThan(1.1);
    // The highlight keeps its position relative to the page and grows with it.
    expect(Math.abs(after!.left / zoomRatio - before!.left)).toBeLessThan(2);
    expect(Math.abs(after!.width / zoomRatio - before!.width)).toBeLessThan(2);
  });

  test("点击引用会跳到对应页码并高亮", async ({ page }) => {
    await page.goto(`/reader?document_id=${DOC_ID}&version_id=${VERSION_ID}`);
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 60_000 });

    const firstCitation = page.locator("aside button").filter({ hasText: "第" }).first();
    await expect(firstCitation).toBeVisible({ timeout: 30_000 });
    await firstCitation.click();

    await expect(page.locator("div.bg-primary-400\\/28").first()).toBeVisible({ timeout: 30_000 });
  });
});
