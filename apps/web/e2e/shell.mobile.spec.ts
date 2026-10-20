import { expect, test } from "@playwright/test";

test.describe("移动端", () => {
  test("底部标签栏可以在模块之间切换", async ({ page }) => {
    await page.goto("/chat");

    const nav = page.getByRole("navigation", { name: "主导航" });
    await expect(nav).toBeVisible();

    await nav.getByRole("link", { name: "知识库" }).click();
    await expect(page).toHaveURL(/\/knowledge/);
    await expect(page.getByText("上传资料")).toBeVisible();

    await nav.getByRole("link", { name: "检索调试" }).click();
    await expect(page).toHaveURL(/\/debug/);
  });

  test("会话列表通过抽屉打开", async ({ page }) => {
    await page.goto("/chat");

    // The context panel is a drawer below the lg breakpoint.
    const toggle = page.getByRole("button", { name: /会话/ }).first();
    await toggle.click();

    // The panel is rendered twice (docked column + mobile drawer); assert on
    // the drawer.
    const drawer = page.getByRole("dialog", { name: "会话" });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("button", { name: "新建对话" })).toBeVisible();
    await expect(drawer.getByPlaceholder("搜索会话")).toBeVisible();
  });

  test("问答可以正常发送并显示引用", async ({ page }) => {
    await page.goto("/chat");

    const input = page.getByPlaceholder(/提出一个水产养殖问题/);
    await expect(input).toBeVisible();
    await input.fill("中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？");
    await input.press("Enter");

    await expect(page.locator("button", { hasText: /^S?\d+$/ }).first()).toBeVisible({
      timeout: 90_000,
    });
  });

  test("知识库上传区在移动端可用", async ({ page }) => {
    await page.goto("/knowledge");
    await expect(page.getByText("拖拽 PDF 到此处上传")).toBeVisible();
    await expect(page.getByRole("button", { name: "选择文件" })).toBeVisible();
  });

  test("文献阅读器在移动端渲染 PDF", async ({ page }) => {
    await page.goto(
      "/reader?document_id=3f534c05-99c9-493e-9e18-323f9ee9a3c1&version_id=2b5511ca-7886-4e40-964e-5a069da06694",
    );
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
  });

  test("整页不滚动，聊天区内部滚动", async ({ page }) => {
    await page.goto("/chat");
    await page.waitForTimeout(1000);

    const metrics = await page.evaluate(() => ({
      docScrollHeight: document.documentElement.scrollHeight,
      viewport: window.innerHeight,
    }));
    expect(metrics.docScrollHeight).toBeLessThanOrEqual(metrics.viewport + 2);
  });
});
