import { expect, test } from "@playwright/test";

import { API_BASE, streamChat } from "./helpers";

test.describe("检索调试与评测", () => {
  test("展示真实的阶段链路，未启用能力明确标注", async ({ page }) => {
    await page.goto("/debug");

    // The stage list is rendered from the real trace configuration.
    await expect(page.getByText("规则 Query IR")).toBeVisible();
    await expect(page.getByText("Dense 召回")).toBeVisible();
    await expect(page.getByText("BM25 召回")).toBeVisible();
    await expect(page.getByText("RRF 融合")).toBeVisible();
    await expect(page.getByText("Reranker 重排")).toBeVisible();
    await expect(page.getByText("证据门槛")).toBeVisible();

    // Disabled capabilities must say so instead of pretending to work.
    await expect(page.getByText("未启用").first()).toBeVisible();
  });

  test("遥测统计来自真实请求日志", async ({ page }) => {
    await page.goto("/debug");
    await expect(page.getByText("查询数")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("证据不足拒答")).toBeVisible();
    await expect(page.getByText("P95 检索耗时")).toBeVisible();
  });

  test("输入 request_id 载入真实 Trace", async ({ page }) => {
    // Produce a real request first so the trace exists.
    const { events } = await streamChat(page, "中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？", {
      mode: "hybrid",
    });
    const meta = events.find((event) => event.event === "meta");
    const requestId = (meta?.data as { request_id?: string } | undefined)?.request_id;
    expect(requestId).toBeTruthy();

    await page.goto(`/debug?request_id=${requestId}`);
    await expect(page.getByText("Typed Query IR")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("候选与融合")).toBeVisible();
    await expect(page.getByText("重排与最终证据")).toBeVisible();
    await expect(page.getByText("原始 Trace")).toBeVisible();

    // The question from the request is echoed back.
    await expect(page.getByText("中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？")).toBeVisible();
  });

  test("不存在的 request_id 给出明确错误而不是空白页", async ({ page }) => {
    await page.goto("/debug");
    await page.getByLabel("request_id").fill("does-not-exist");
    await page.getByRole("button", { name: "加载 Trace" }).click();

    await expect(page.getByText("未找到该请求的 Trace")).toBeVisible({ timeout: 30_000 });
  });
});
