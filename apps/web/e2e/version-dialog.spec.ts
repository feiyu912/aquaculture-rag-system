import { expect, test } from "@playwright/test";

import { cleanupE2EDocuments, uploadPdf, waitForJob } from "./helpers";

test.afterAll(async ({ request }) => {
  await cleanupE2EDocuments(request);
});

test.describe("知识库：版本更新弹窗", () => {
  test("通过弹窗上传新版本，解析成功后新版本生效", async ({ page }) => {
    const title = `E2E 弹窗版本 ${Date.now()}`;
    const first = await uploadPdf(page, "e2e-3page.pdf", { title, category: "E2E测试" });

    await page.goto("/knowledge");
    // The list is fetched on mount; poll with a reload until the freshly
    // ingested document shows up.
    await expect(async () => {
      await page.reload();
      await expect(page.getByText(title, { exact: false }).first()).toBeVisible({ timeout: 5000 });
    }).toPass({ timeout: 30_000 });

    // Open the row menu and pick "上传新版本".
    const menuButton = page.getByRole("button", { name: /的操作$/ }).nth(0);
    await menuButton.click();
    await page.getByRole("menuitem", { name: "上传新版本" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("上传新版本")).toBeVisible();

    // Pick the revised file and submit.
    await dialog.locator('input[type="file"]').setInputFiles("e2e/fixtures/e2e-3page-v2.pdf");
    await dialog.getByRole("button", { name: "上传并入库" }).click();

    await expect(dialog.getByText("新版本已生效")).toBeVisible({ timeout: 90_000 });

    // The backend really switched the active version.
    const detail = await page.request.get(
      `http://127.0.0.1:8000/api/documents/${first.document_id}`,
    );
    const body = (await detail.json()) as { current_version_no: number; versions: unknown[] };
    expect(body.current_version_no).toBe(2);
    expect(body.versions.length).toBe(2);
  });
});
