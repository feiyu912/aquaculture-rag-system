import { expect, test } from "@playwright/test";

import { cleanupE2EDocuments, uploadPdf, waitForJob } from "./helpers";

const FIXTURE = "e2e-single.pdf";

test.afterAll(async ({ request }) => {
  await cleanupE2EDocuments(request);
});

test.describe("知识库管理", () => {
  test("上传 PDF 后由 worker 入库，文档出现在列表中", async ({ page }) => {
    const title = `E2E 上传 ${Date.now()}`;
    const uploaded = await uploadPdf(page, FIXTURE, {
      title,
      category: "E2E测试",
      species: "中华绒螯蟹",
    });

    await page.goto("/knowledge");

    await expect(async () => {
      await page.reload();
      await expect(page.getByText(title, { exact: false }).first()).toBeVisible({ timeout: 5000 });
    }).toPass({ timeout: 30_000 });

    // The document is active and indexed.
    await expect(page.getByText("生效中").first()).toBeVisible();

    await page.request.delete(`http://127.0.0.1:8000/api/documents/${uploaded.document_id}`);
  });

  test("版本历史对话框可以回滚到旧版本", async ({ page }) => {
    const title = `E2E 版本 ${Date.now()}`;
    const first = await uploadPdf(page, "e2e-3page.pdf", { title, category: "E2E测试" });

    // Publish a second version of the same document.
    const form = await page.request.post(
      `http://127.0.0.1:8000/api/documents/${first.document_id}/versions`,
      {
        multipart: {
          file: {
            name: "e2e-3page-v2.pdf",
            mimeType: "application/pdf",
            buffer: (await import("node:fs")).readFileSync("e2e/fixtures/e2e-3page-v2.pdf"),
          },
        },
      },
    );
    expect(form.ok()).toBeTruthy();
    const second = (await form.json()) as { job_id: string };
    await waitForJob(page, second.job_id);

    const detail = await page.request.get(
      `http://127.0.0.1:8000/api/documents/${first.document_id}`,
    );
    const body = (await detail.json()) as { current_version_no: number; versions: unknown[] };
    expect(body.current_version_no).toBe(2);
    expect(body.versions.length).toBe(2);

    // Roll back to v1 through the API the dialog uses.
    const v1 = (body.versions as { version_no: number; id: string }[]).find(
      (version) => version.version_no === 1,
    );
    expect(v1).toBeTruthy();

    const rollback = await page.request.post(
      `http://127.0.0.1:8000/api/documents/${first.document_id}/rollback`,
      { data: { version_id: v1!.id } },
    );
    expect(rollback.ok()).toBeTruthy();

    const after = await page.request.get(
      `http://127.0.0.1:8000/api/documents/${first.document_id}`,
    );
    const afterBody = (await after.json()) as { current_version_no: number };
    expect(afterBody.current_version_no).toBe(1);

    await page.request.delete(`http://127.0.0.1:8000/api/documents/${first.document_id}`);
  });

  test("删除文档后从列表消失", async ({ page }) => {
    const title = `E2E 删除 ${Date.now()}`;
    const uploaded = await uploadPdf(page, FIXTURE, { title, category: "E2E测试" });

    await page.goto("/knowledge");
    const row = page.getByRole("button", { name: new RegExp(title.slice(0, 12)) }).first();
    await expect(row).toBeVisible();

    const removed = await page.request.delete(
      `http://127.0.0.1:8000/api/documents/${uploaded.document_id}`,
    );
    expect(removed.ok()).toBeTruthy();

    await page.reload();
    await expect(page.getByRole("button", { name: new RegExp(title.slice(0, 12)) })).toHaveCount(0);
  });
});
