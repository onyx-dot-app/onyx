import { test, expect } from "@playwright/test";
import { CraftOutputsPage } from "@tests/e2e/pages/CraftOutputsPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import type { OutputInventory } from "@/app/craft/types/streamingTypes";
import type { Settings } from "@/lib/settings/types";

test.describe("Craft outputs", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const settingsResponse = await page.request.get("/api/settings");
    expect(settingsResponse.ok()).toBe(true);
    const settings: Settings = await settingsResponse.json();
    test.skip(
      settings.onyx_craft_enabled !== true,
      "Onyx Craft is disabled in this environment"
    );
  });
  test("retains tabs and search through close, full, restore, and reorder", async ({
    page,
  }) => {
    const outputs = new CraftOutputsPage(page);
    await outputs.goto();
    await outputs.expectMode("closed");
    await outputs.expectHeaderStable(() => outputs.open());
    await outputs.expectTabs(["Outputs"]);
    await outputs.closeTab("Outputs");
    await outputs.openTab("All Files");
    await outputs.search("notes");
    await outputs.openTab("Apps");
    await outputs.expectTabs(["All Files", "Apps"]);
    await outputs.reorderBrowserLeft();
    await outputs.expectTabs(["Apps", "All Files"]);
    await outputs.expectHeaderStable(async () => {
      await outputs.expandToFullMode();
    });
    await outputs.screenshot("craft-outputs-full");
    await outputs.expectHeaderStable(async () => {
      await outputs.exitFullMode();
    });
    await outputs.expectHeaderStable(() => outputs.close());
    await outputs.open();
    await outputs.expectTabs(["Apps", "All Files"]);
    await outputs.openTab("All Files");
    await outputs.expectSearch("notes");
    await outputs.resizeKeyboard();
    await outputs.screenshot("craft-outputs-medium");
    await outputs.closeTab("All Files");
    await outputs.closeTab("Apps");
    await outputs.expectEmpty();
    await outputs.close();
    await outputs.open();
    await outputs.expectEmpty();
  });
  test("keeps outputs controls usable in a narrow workspace", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 320, height: 720 });
    const outputs = new CraftOutputsPage(page);
    await outputs.goto();
    await outputs.open();
    await outputs.openTab("Apps");
    await outputs.expectHeaderStable(async () => {
      await outputs.expandToFullMode();
    });
    await outputs.screenshot("craft-outputs-narrow");
    await outputs.close();
  });
  test("shows saved output previews during reload validation and accepts the fresh inventory", async ({
    page,
  }) => {
    const api = new OnyxApiClient(page.request);
    const sessionId = await api.createCraftSession("E2E output cache");
    const outputs = new CraftOutputsPage(page);
    const cachedPath = "outputs/cached.svg";
    const replacementPath = "outputs/replacement.svg";
    let inventory: OutputInventory = {
      files: [{ path: cachedPath, revision: "cached-revision", size: 120 }],
      complete: true,
    };
    let releaseValidation = () => {};
    let validationGate: Promise<void> | null = null;
    let previewRequests = 0;
    let inventoryRequests = 0;
    const directoryRequests: string[] = [];
    await page.route(`**/api/build/sessions/${sessionId}/files*`, (route) => {
      const directory =
        new URL(route.request().url()).searchParams.get("path") ?? "";
      directoryRequests.push(directory);
      return route.fulfill({
        json: {
          path: directory,
          entries:
            directory === ""
              ? [
                  {
                    name: "outputs",
                    path: "outputs",
                    is_directory: true,
                    size: null,
                    mime_type: null,
                  },
                ]
              : inventory.files.map((file) => ({
                  name: file.path.split("/").at(-1),
                  path: file.path,
                  is_directory: false,
                  size: file.size,
                  mime_type: "image/svg+xml",
                })),
        },
      });
    });
    // A real owned session supplies runtime/auth state. Only generated file bytes are deterministic fixtures.
    await page.route(
      `**/api/build/sessions/${sessionId}/outputs`,
      async (route) => {
        inventoryRequests++;
        if (validationGate) await validationGate;
        await route.fulfill({ json: inventory });
      }
    );
    await page.route(
      `**/api/build/sessions/${sessionId}/artifacts/outputs/*.svg`,
      async (route) => {
        previewRequests++;
        await route.fulfill({
          contentType: "image/svg+xml",
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="100"><rect width="160" height="100" fill="seagreen"/></svg>',
        });
      }
    );
    try {
      await outputs.goto(sessionId);
      await expect.poll(() => directoryRequests).toEqual(["", "outputs"]);
      await expect.poll(() => inventoryRequests).toBe(1);
      await outputs.open();
      await outputs.expectTabs(["Outputs"]);
      await outputs.expectOutputPreview(cachedPath);
      await expect.poll(() => previewRequests).toBe(1);
      const savedWidth = await outputs.quickResizeLeft(64);
      const acceptedRequests = inventoryRequests;
      validationGate = new Promise<void>((resolve) => {
        releaseValidation = resolve;
      });
      inventory = {
        files: [
          {
            path: replacementPath,
            revision: "replacement-revision",
            size: 120,
          },
        ],
        complete: true,
      };
      await outputs.reload();
      await outputs.expectMode("medium");
      await outputs.expectTabs(["Outputs"]);
      await outputs.expectPanelWidth(savedWidth);
      await expect
        .poll(() => inventoryRequests)
        .toBeGreaterThan(acceptedRequests);
      // The new backend response remains blocked: both the list and preview must come from the real cache.
      await outputs.expectOutputPreview(cachedPath);
      await outputs.expectOutputAbsent(replacementPath);
      expect(previewRequests).toBe(1);
      validationGate = null;
      releaseValidation();
      await outputs.expectOutputPreview(replacementPath);
      await outputs.expectOutputAbsent(cachedPath);
      await expect.poll(() => previewRequests).toBe(2);
      await outputs.close();
      await outputs.open();
      await outputs.expectOutputPreview(replacementPath);
      expect(previewRequests).toBe(2);
      await outputs.closeTab("Outputs");
      await outputs.openTab("Outputs");
      await outputs.expectOutputPreview(replacementPath);
      expect(previewRequests).toBe(2);
      const completedDirectoryReads = directoryRequests.length;
      await outputs.openTab("All Files");
      await outputs.closeTab("All Files");
      await outputs.openTab("All Files");
      expect(directoryRequests).toHaveLength(completedDirectoryReads);
      expect(inventoryRequests).toBe(2);
    } finally {
      validationGate = null;
      releaseValidation();
      await api.deleteCraftSession(sessionId);
    }
  });
});
