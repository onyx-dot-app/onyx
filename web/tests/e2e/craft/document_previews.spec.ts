import path from "node:path";
import { test, expect } from "@playwright/test";
import { CraftDocumentPreviewPage } from "@tests/e2e/pages/CraftDocumentPreviewPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import type { OutputInventory } from "@/app/craft/types/streamingTypes";
import type { Settings } from "@/lib/settings/types";

test("renders PDF pages and retains document navigation across tabs and panel closure", async ({
  page,
}, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
  const settingsResponse = await page.request.get("/api/settings");
  expect(settingsResponse.ok()).toBe(true);
  const settings: Settings = await settingsResponse.json();
  test.skip(
    settings.onyx_craft_enabled !== true,
    "Onyx Craft is disabled in this environment"
  );
  const api = new OnyxApiClient(page.request);
  const sessionId = await api.createCraftSession("E2E document previews");
  const preview = new CraftDocumentPreviewPage(page);
  const inventory: OutputInventory = {
    files: [
      { path: "outputs/report.pdf", revision: "pdf-one", size: 959 },
      { path: "outputs/deck.pptx", revision: "deck-one", size: 1024 },
    ],
    complete: true,
  };
  let pdfRequests = 0;
  let presentationRequests = 0;
  let workerRequests = 0;
  page.on("request", (request) => {
    if (
      request.url().includes("/pdfjs/") &&
      request.url().endsWith("pdf.worker.min.mjs")
    )
      workerRequests++;
  });
  const slide =
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="seagreen"/></svg>';
  await page.route(`**/api/build/sessions/${sessionId}/outputs`, (route) =>
    route.fulfill({ json: inventory })
  );
  await page.route(
    `**/api/build/sessions/${sessionId}/output-thumbnail/**`,
    (route) => route.fulfill({ contentType: "image/svg+xml", body: slide })
  );
  await page.route(
    `**/api/build/sessions/${sessionId}/artifacts/outputs/report.pdf`,
    async (route) => {
      pdfRequests++;
      await route.fulfill({
        contentType: "application/pdf",
        path: path.resolve(
          process.cwd(),
          "../backend/tests/unit/onyx/file_processing/fixtures/multipage.pdf"
        ),
      });
    }
  );
  await page.route(
    `**/api/build/sessions/${sessionId}/pptx-preview/outputs/deck.pptx`,
    async (route) => {
      presentationRequests++;
      await route.fulfill({
        json: {
          slide_count: 2,
          slide_paths: ["outputs/slide-1.svg", "outputs/slide-2.svg"],
          cached: true,
        },
      });
    }
  );
  await page.route(
    `**/api/build/sessions/${sessionId}/artifacts/outputs/slide-*.svg?*`,
    (route) => route.fulfill({ contentType: "image/svg+xml", body: slide })
  );
  try {
    await preview.outputs.goto(sessionId);
    await preview.outputs.open();
    await preview.openFile("outputs/report.pdf");
    await preview.expectPdfPage(1);
    await expect.poll(() => workerRequests).toBeGreaterThan(0);
    await preview.nextPdfPage();
    await preview.expectPdfPage(2);
    await preview.selectPdfThumbnail(1);
    await preview.expectPdfPage(1);
    await preview.nextPdfPage();
    await preview.setPdfZoom("150%");
    await preview.resizePdfThumbnails();
    await preview.togglePdfThumbnails(false);
    await preview.togglePdfThumbnails(true);
    await preview.selectTab("Outputs");
    await preview.openFile("outputs/deck.pptx");
    await preview.expectPresentationSlide(1);
    await preview.nextPresentationSlide();
    await preview.expectPresentationSlide(2);
    await preview.resizePresentationThumbnails();
    await preview.selectTab("report.pdf");
    await preview.expectPdfPage(2);
    await preview.expectPdfZoom("150%");
    await preview.outputs.close();
    await preview.outputs.open();
    await preview.expectPdfPage(2);
    await preview.expectPdfZoom("150%");
    await preview.selectTab("deck.pptx");
    await preview.expectPresentationSlide(2);
    expect(pdfRequests).toBe(1);
    expect(presentationRequests).toBe(1);
  } finally {
    await api.deleteCraftSession(sessionId);
  }
});
