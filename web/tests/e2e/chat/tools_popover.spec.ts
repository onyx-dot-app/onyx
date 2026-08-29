import { test, expect, type Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import {
  TOOL_IDS,
  openActionManagement,
  openSourceManagement,
  toggleToolDisabled,
  getSourceToggle,
} from "@tests/e2e/utils/tools";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { sendMessage } from "@tests/e2e/utils/chatActions";

const LOCAL_STORAGE_KEY = "selectedInternalSearchSources";

test.describe("ToolsPopover Tool Toggles", () => {
  test.describe.configure({ mode: "serial" });

  let ccPairId: number | null = null;
  let webSearchProviderId: number | null = null;
  let imageGenConfigId: string | null = null;

  test.beforeAll(async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: "admin_auth.json" });
    const page = await ctx.newPage();
    await page.goto("http://localhost:3000/app");
    await page.waitForLoadState("networkidle");

    const apiClient = new OnyxApiClient(page.request);

    // Create a file connector so internal search tool is available
    ccPairId = await apiClient.createFileConnector(
      `actions-popover-test-${Date.now()}`
    );

    // Create providers for web search and image generation (best-effort)
    try {
      webSearchProviderId = await apiClient.createWebSearchProvider(
        "exa",
        `actions-popover-web-search-${Date.now()}`
      );
    } catch (error) {
      console.warn(`Failed to create web search provider: ${error}`);
    }

    try {
      imageGenConfigId = await apiClient.createImageGenerationConfig(
        `actions-popover-image-gen-${Date.now()}`
      );
    } catch (error) {
      console.warn(`Failed to create image gen config: ${error}`);
    }

    // Ensure all tools are enabled on the default agent
    const toolsResp = await page.request.get("/api/tool");
    const allTools = await toolsResp.json();
    const toolIdsByCodeId: Record<string, number> = {};
    allTools.forEach((t: any) => {
      if (t.in_code_tool_id) toolIdsByCodeId[t.in_code_tool_id] = t.id;
    });

    const configResp = await page.request.get(
      "/api/admin/default-assistant/configuration"
    );
    const currentConfig = await configResp.json();

    const desiredToolIds = [
      toolIdsByCodeId["SearchTool"],
      toolIdsByCodeId["WebSearchTool"],
      toolIdsByCodeId["ImageGenerationTool"],
    ].filter(Boolean);

    const uniqueToolIds = Array.from(
      new Set([...(currentConfig.tool_ids || []), ...desiredToolIds])
    );

    await page.request.patch("/api/admin/default-assistant", {
      data: { tool_ids: uniqueToolIds },
    });

    await ctx.close();
  });

  test.afterAll(async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: "admin_auth.json" });
    const page = await ctx.newPage();
    await page.goto("http://localhost:3000/app");
    await page.waitForLoadState("networkidle");

    const apiClient = new OnyxApiClient(page.request);

    if (ccPairId !== null) {
      try {
        await apiClient.deleteCCPair(ccPairId);
      } catch (error) {
        console.warn(`Cleanup: failed to delete connector: ${error}`);
      }
    }
    if (webSearchProviderId !== null) {
      try {
        await apiClient.deleteWebSearchProvider(webSearchProviderId);
      } catch (error) {
        console.warn(`Cleanup: failed to delete web search provider: ${error}`);
      }
    }
    if (imageGenConfigId !== null) {
      try {
        await apiClient.deleteImageGenerationConfig(imageGenConfigId);
      } catch (error) {
        console.warn(`Cleanup: failed to delete image gen config: ${error}`);
      }
    }

    await ctx.close();
  });

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    // Clear source preferences for a clean slate
    await page.evaluate(
      (key) => localStorage.removeItem(key),
      LOCAL_STORAGE_KEY
    );
    // Tool configurations belong to a chat and live in session storage, so a
    // chat left behind by an earlier test would otherwise be read by this one.
    await page.evaluate(() => sessionStorage.clear());
  });

  test("should show internal search and other tools in popover", async ({
    page,
  }) => {
    await openActionManagement(page);

    // Internal search must be visible (connector was created in beforeAll)
    await expect(page.locator(TOOL_IDS.searchOption)).toBeVisible({
      timeout: 10000,
    });

    // Soft-check other tools (depend on provider setup success)
    const webVisible = await page
      .locator(TOOL_IDS.webSearchOption)
      .isVisible()
      .catch(() => false);
    const imgVisible = await page
      .locator(TOOL_IDS.imageGenerationOption)
      .isVisible()
      .catch(() => false);
    console.log(`[tools] web_search=${webVisible}, image_gen=${imgVisible}`);
  });

  test("source preferences should persist to localStorage and survive reload", async ({
    page,
  }) => {
    await openActionManagement(page);
    await expect(page.locator(TOOL_IDS.searchOption)).toBeVisible({
      timeout: 10000,
    });
    await openSourceManagement(page);

    // Find the first source switch
    const switches = page.locator('[role="switch"]');
    await expect(switches.first()).toBeVisible({ timeout: 5000 });

    const firstSwitch = switches.first();
    const ariaLabel = await firstSwitch.getAttribute("aria-label");
    const sourceName = ariaLabel?.replace("Toggle ", "") || "";
    expect(sourceName).toBeTruthy();

    // Ensure it's enabled, then disable it
    if ((await firstSwitch.getAttribute("aria-checked")) === "false") {
      await firstSwitch.click();
      await expect(firstSwitch).toHaveAttribute("aria-checked", "true");
    }
    await firstSwitch.click();
    await expect(firstSwitch).toHaveAttribute("aria-checked", "false");

    // Verify localStorage was updated
    const stored = await page.evaluate(
      (key) => localStorage.getItem(key),
      LOCAL_STORAGE_KEY
    );
    expect(stored).toBeTruthy();
    expect(JSON.parse(stored!).sourcePreferences).toBeDefined();

    // Reload and verify persistence
    await page.reload();
    await page.waitForLoadState("networkidle");

    await openActionManagement(page);
    await openSourceManagement(page);

    const sourceToggle = getSourceToggle(page, sourceName);
    await expect(sourceToggle).toHaveAttribute("aria-checked", "false", {
      timeout: 10000,
    });
  });

  test("disabling search tool clears sources, re-enabling restores them", async ({
    page,
  }) => {
    await openActionManagement(page);
    await expect(page.locator(TOOL_IDS.searchOption)).toBeVisible({
      timeout: 10000,
    });

    // Open source management and count enabled sources
    await openSourceManagement(page);
    const switches = page.locator('[role="switch"]');
    await expect(switches.first()).toBeVisible({ timeout: 5000 });

    const totalSources = await switches.count();
    let enabledBefore = 0;
    for (let i = 0; i < totalSources; i++) {
      if ((await switches.nth(i).getAttribute("aria-checked")) === "true") {
        enabledBefore++;
      }
    }
    expect(enabledBefore).toBeGreaterThan(0);

    // Go back to primary view
    await page.locator('button[aria-label="Back"]').click();
    await expect(page.locator(TOOL_IDS.searchOption)).toBeVisible();

    // Disable the search tool
    await toggleToolDisabled(page, TOOL_IDS.searchOption);

    // Verify localStorage was written (the fix being tested)
    const stored = await page.evaluate(
      (key) => localStorage.getItem(key),
      LOCAL_STORAGE_KEY
    );
    expect(stored).toBeTruthy();

    // Re-enable the search tool
    await toggleToolDisabled(page, TOOL_IDS.searchOption);

    // Verify sources were restored
    await openSourceManagement(page);
    const switchesAfter = page.locator('[role="switch"]');
    const totalAfter = await switchesAfter.count();
    let enabledAfter = 0;
    for (let i = 0; i < totalAfter; i++) {
      if (
        (await switchesAfter.nth(i).getAttribute("aria-checked")) === "true"
      ) {
        enabledAfter++;
      }
    }
    expect(enabledAfter).toBe(enabledBefore);
  });

  // Image generation rather than internal search: the search tool's state is
  // re-derived on mount from the selected sources, which are still global in
  // `localStorage`, so it would answer for those rather than for the chat.
  const CONFIGURED_TOOL = TOOL_IDS.imageGenerationOption;

  /** The slash button reads "Disable" while the tool is on, "Enable" once off. */
  async function expectToolDisabled(
    page: Page,
    disabled: boolean
  ): Promise<void> {
    await openActionManagement(page);
    const option = page.locator(CONFIGURED_TOOL);
    await expect(option).toBeVisible({ timeout: 10000 });
    await option.hover();
    await expect(
      option
        .locator('button[aria-label="Disable"], button[aria-label="Enable"]')
        .first()
    ).toHaveAttribute("aria-label", disabled ? "Enable" : "Disable");
  }

  test("a new session forgets a disabled tool", async ({ page }) => {
    await expectToolDisabled(page, false);
    await toggleToolDisabled(page, CONFIGURED_TOOL);
    await expectToolDisabled(page, true);

    // Nothing was chosen for a chat, because there is no chat yet.
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expectToolDisabled(page, false);
  });

  test("a chat keeps a disabled tool across a reload", async ({ page }) => {
    await sendMessage(page, "hello");
    await page.waitForURL(/chatId=/, { timeout: 30000 });

    await expectToolDisabled(page, false);
    await toggleToolDisabled(page, CONFIGURED_TOOL);
    await expectToolDisabled(page, true);

    await page.reload();
    await page.waitForLoadState("networkidle");
    await expectToolDisabled(page, true);
  });
});
