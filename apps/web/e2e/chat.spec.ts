import { expect, test } from "@playwright/test";

import { streamChat, uploadPdf } from "./helpers";

test.describe("智能问答（SSE 流式）", () => {
  test("回答以 token 形式流式返回，并渲染可点击引用", async ({ page }) => {
    await page.goto("/chat");
    await expect(page.getByPlaceholder(/提出一个水产养殖问题/)).toBeVisible();

    const { events, text, sources } = await streamChat(page, "中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？", {
      mode: "hybrid",
    });

    const names = events.map((event) => String(event.event));
    expect(names).toContain("meta");
    expect(names).toContain("status");
    expect(names).toContain("sources");
    expect(names).toContain("token");
    expect(names).toContain("citation_check");
    expect(names).toContain("done");

    expect(text.length).toBeGreaterThan(20);
    expect(sources.length).toBeGreaterThan(0);
  });

  test("界面上实时追加回答并出现引用芯片", async ({ page }) => {
    // The generation time is dominated by the real LLM gateway.
    test.setTimeout(180_000);
    await page.goto("/chat");

    const input = page.getByPlaceholder(/提出一个水产养殖问题/);
    await input.fill("凡纳滨对虾养殖水质的酸碱度要求是什么？");
    await input.press("Enter");

    // The meta strip only renders once the answer completed, so waiting for it
    // avoids racing the streaming tokens.
    await expect(page.getByText(/总计 \d/)).toBeVisible({ timeout: 150_000 });

    const chip = page.locator("button", { hasText: /^S?\d+$/ }).first();
    await expect(chip).toBeVisible();
  });

  test("知识库之外的问题给出证据不足提示", async ({ page }) => {
    await page.goto("/chat");

    const input = page.getByPlaceholder(/提出一个水产养殖问题/);
    await input.fill("How do I bake sourdough bread at home?");
    await input.press("Enter");

    await expect(page.getByText("证据不足，无法作答")).toBeVisible({ timeout: 90_000 });
  });

  test("引用面板可以打开并列出真实来源", async ({ page }) => {
    await page.goto("/chat");

    const input = page.getByPlaceholder(/提出一个水产养殖问题/);
    await input.fill("中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？");
    await input.press("Enter");

    const panelButton = page.getByRole("button", { name: "引用来源面板" });
    await expect(panelButton).toBeVisible();

    // The badge shows how many sources came back from the server.
    await expect(panelButton).toContainText(/\d/, { timeout: 90_000 });

    await panelButton.click();
    await expect(page.getByText("引用来源").first()).toBeVisible();
  });
});
