import { test, expect, type Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import {
  TOOL_IDS,
  TOOL_NAMES,
  toolOption,
  openActionManagement,
  openSourceManagement,
  toggleToolDisabled,
  getSourceToggle,
} from "@tests/e2e/utils/tools";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { sendMessage } from "@tests/e2e/utils/chatActions";

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
    // Tool configurations belong to a chat and live in session storage, so a
    // chat left behind by an earlier test would otherwise be read by this one.
    await page.evaluate(() => sessionStorage.clear());
  });

  test("should show internal search and other tools in popover", async ({
    page,
  }) => {
    await openActionManagement(page);

    // Internal search must be visible (connector was created in beforeAll)
    await expect(toolOption(page, TOOL_NAMES.internalSearch)).toBeVisible({
      timeout: 10000,
    });

    // Soft-check other tools (depend on provider setup success)
    const webVisible = await toolOption(page, TOOL_NAMES.webSearch)
      .isVisible()
      .catch(() => false);
    const imgVisible = await toolOption(page, TOOL_NAMES.imageGeneration)
      .isVisible()
      .catch(() => false);
    console.log(`[tools] web_search=${webVisible}, image_gen=${imgVisible}`);
  });

  test("a chat keeps a source selection across a reload", async ({ page }) => {
    // Sources belong to a chat. A composer with no chat yet keeps nothing.
    await sendMessage(page, "hello");
    await page.waitForURL(/chatId=/, { timeout: 30000 });

    await openActionManagement(page);
    await expect(toolOption(page, TOOL_NAMES.internalSearch)).toBeVisible({
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

    await page.reload();
    await page.waitForLoadState("networkidle");

    await openActionManagement(page);
    await openSourceManagement(page);

    const sourceToggle = getSourceToggle(page, sourceName);
    await expect(sourceToggle).toHaveAttribute("aria-checked", "false", {
      timeout: 10000,
    });
  });

  /** Number of source switches in the open source management view. */
  async function countEnabledSources(page: Page): Promise<number> {
    const switches = page.locator('[role="switch"]');
    await expect(switches.first()).toBeVisible({ timeout: 5000 });
    const total = await switches.count();
    let enabled = 0;
    for (let i = 0; i < total; i++) {
      if ((await switches.nth(i).getAttribute("aria-checked")) === "true") {
        enabled++;
      }
    }
    return enabled;
  }

  test("disabling the search tool leaves the source selection alone", async ({
    page,
  }) => {
    await openActionManagement(page);
    await expect(toolOption(page, TOOL_NAMES.internalSearch)).toBeVisible({
      timeout: 10000,
    });

    await openSourceManagement(page);
    const enabledBefore = await countEnabledSources(page);
    expect(enabledBefore).toBeGreaterThan(0);

    await page.locator('button[aria-label="Back"]').click();
    await expect(toolOption(page, TOOL_NAMES.internalSearch)).toBeVisible();

    // The tool state and the source selection are separate axes: switching
    // the tool off neither clears the sources nor parks them for later.
    await toggleToolDisabled(toolOption(page, TOOL_NAMES.internalSearch));
    await openSourceManagement(page);
    expect(await countEnabledSources(page)).toBe(enabledBefore);

    await page.locator('button[aria-label="Back"]').click();
    await toggleToolDisabled(toolOption(page, TOOL_NAMES.internalSearch));
    await openSourceManagement(page);
    expect(await countEnabledSources(page)).toBe(enabledBefore);
  });

  // Internal search: the connector from `beforeAll` guarantees it is offered.
  // The other tools depend on best-effort provider setup.
  const CONFIGURED_TOOL = TOOL_NAMES.internalSearch;

  /** The slash button reads "Disable" while the tool is on, "Enable" once off. */
  async function expectToolDisabled(
    page: Page,
    disabled: boolean
  ): Promise<void> {
    await openActionManagement(page);
    const option = toolOption(page, CONFIGURED_TOOL);
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
    await toggleToolDisabled(toolOption(page, CONFIGURED_TOOL));
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
    await toggleToolDisabled(toolOption(page, CONFIGURED_TOOL));
    await expectToolDisabled(page, true);

    await page.reload();
    await page.waitForLoadState("networkidle");
    await expectToolDisabled(page, true);
  });
});
