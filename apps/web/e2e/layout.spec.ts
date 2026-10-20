import { expect, test } from "@playwright/test";

test.describe("布局：可拖拽的侧栏与会话标题", () => {
  test("整页不滚动，长列表在内部滚动", async ({ page }) => {
    await page.goto("/chat");
    await page.waitForTimeout(1200);

    const metrics = await page.evaluate(() => ({
      docScrollHeight: document.documentElement.scrollHeight,
      viewport: window.innerHeight,
      listScrollHeight: document.querySelector(".scroll-contain")?.scrollHeight ?? 0,
      listClientHeight: document.querySelector(".scroll-contain")?.clientHeight ?? 0,
    }));

    // The shell owns the viewport; the session list scrolls inside it.
    expect(metrics.docScrollHeight).toBeLessThanOrEqual(metrics.viewport + 2);
    expect(metrics.listScrollHeight).toBeGreaterThan(metrics.listClientHeight);
  });

  test("分隔条可以拖动改变侧栏宽度", async ({ page }) => {
    await page.goto("/chat");
    await page.waitForTimeout(800);

    const aside = page.locator("aside").first();
    const handle = page.getByRole("separator", { name: "调整侧栏宽度" });
    await expect(handle).toBeVisible();

    const before = (await aside.boundingBox())?.width ?? 0;
    expect(before).toBeGreaterThan(100);

    const box = (await handle.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + 200);
    await page.mouse.down();
    await page.mouse.move(box.x + 120, box.y + 200, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(400);

    const after = (await aside.boundingBox())?.width ?? 0;
    expect(after).toBeGreaterThan(before + 60);
  });

  test("宽度在刷新后保持", async ({ page }) => {
    await page.goto("/chat");
    await page.waitForTimeout(800);

    const handle = page.getByRole("separator", { name: "调整侧栏宽度" });
    const box = (await handle.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + 200);
    await page.mouse.down();
    await page.mouse.move(box.x + 90, box.y + 200, { steps: 10 });
    await page.mouse.up();
    await page.waitForTimeout(400);

    const width = (await page.locator("aside").first().boundingBox())?.width ?? 0;

    await page.reload();
    await page.waitForTimeout(900);

    const restored = (await page.locator("aside").first().boundingBox())?.width ?? 0;
    expect(Math.abs(restored - width)).toBeLessThan(4);
  });

  test("会话标题显示完整文本而不是被截断", async ({ page }) => {
    await page.goto("/chat");
    await page.waitForTimeout(1200);

    const items = page.locator("aside li");
    const count = await items.count();
    expect(count).toBeGreaterThan(0);

    // Titles wrap to two lines instead of being cut with an ellipsis.
    const first = items.first();
    const title = first.locator("span").first();
    const text = (await title.innerText()).trim();
    expect(text.length).toBeGreaterThan(0);
    expect(text.endsWith("…")).toBe(false);
  });

  test("顶栏按钮可以收起侧栏", async ({ page }) => {
    await page.goto("/chat");
    await page.waitForTimeout(800);

    const aside = page.locator("aside").first();
    expect((await aside.boundingBox())?.width ?? 0).toBeGreaterThan(100);

    await page.getByRole("button", { name: /收起|展开/ }).first().click();
    await page.waitForTimeout(400);

    expect((await aside.boundingBox())?.width ?? 0).toBeLessThan(4);
  });
});
