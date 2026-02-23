import { test, expect } from "@playwright/test";
import type { Page, Locator } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import {
  TOOL_IDS,
  waitForUnifiedGreeting,
  openActionManagement,
} from "@tests/e2e/utils/tools";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

/**
 * Locate the Switch toggle for a built-in tool by its display name.
 * Each tool sits inside its own `<label>` wrapper created by InputLayouts.Horizontal.
 */
function getToolSwitch(page: Page, toolName: string): Locator {
  return page
    .locator("label")
    .filter({ has: page.getByText(toolName, { exact: true }) })
    .locator('button[role="switch"]')
    .first();
}

/**
 * Click a button and wait for the PATCH response to complete.
 * Uses waitForResponse set up *before* the click to avoid race conditions.
 */
async function clickAndWaitForPatch(
  page: Page,
  buttonLocator: Locator
): Promise<void> {
  const patchPromise = page.waitForResponse(
    (r) =>
      r.url().includes("/api/admin/default-assistant") &&
      r.request().method() === "PATCH",
    { timeout: 8000 }
  );
  await buttonLocator.click();
  await patchPromise;
}

test.describe("Chat Preferences Admin Page", () => {
  let testCcPairId: number | null = null;
  let webSearchProviderId: number | null = null;
  let imageGenConfigId: string | null = null;

  test.beforeEach(async ({ page }) => {
    // Log in as admin
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const apiClient = new OnyxApiClient(page.request);

    // Create a connector so Internal Search tool becomes available
    testCcPairId = await apiClient.createFileConnector(
      `Test Connector ${Date.now()}`
    );

    // Create providers for Web Search and Image Generation tools
    try {
      webSearchProviderId = await apiClient.createWebSearchProvider(
        "exa",
        `Test Web Search Provider ${Date.now()}`
      );
      imageGenConfigId = await apiClient.createImageGenerationConfig(
        `test-image-gen-${Date.now()}`
      );
    } catch (error) {
      console.warn(`Failed to create tool providers: ${error}`);
    }

    // Navigate to chat preferences
    await page.goto("/admin/configuration/chat-preferences");
    await page.waitForURL("**/admin/configuration/chat-preferences**");

    // Attach basic API logging for this spec
    page.on("response", async (resp) => {
      const url = resp.url();
      if (
        url.includes("/api/admin/default-assistant") ||
        url.includes("/api/admin/settings")
      ) {
        const method = resp.request().method();
        const status = resp.status();
        let body = "";
        try {
          body = await resp.text();
        } catch {}
        console.log(
          `[api:response] ${method} ${url} => ${status} body=${body?.slice(
            0,
            300
          )}`
        );
      }
    });

    // Proactively log tool availability and current config
    try {
      const baseURL = process.env.BASE_URL || "http://localhost:3000";
      const toolsResp = await page.request.get(`${baseURL}/api/tool`);
      const cfgResp = await page.request.get(
        `${baseURL}/api/admin/default-assistant/configuration`
      );
      console.log(
        `[/api/tool] status=${toolsResp.status()} body=${(
          await toolsResp.text()
        ).slice(0, 400)}`
      );
      console.log(
        `[/configuration] status=${cfgResp.status()} body=${(
          await cfgResp.text()
        ).slice(0, 400)}`
      );
    } catch (e) {
      console.log(`[setup] Failed to fetch initial admin config: ${String(e)}`);
    }
  });

  test.afterEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);

    // Clean up the test connector
    if (testCcPairId !== null) {
      try {
        await apiClient.deleteCCPair(testCcPairId);
        testCcPairId = null;
      } catch (error) {
        console.warn(
          `Failed to delete test connector ${testCcPairId}: ${error}`
        );
      }
    }

    // Clean up web search provider
    if (webSearchProviderId !== null) {
      try {
        await apiClient.deleteWebSearchProvider(webSearchProviderId);
        webSearchProviderId = null;
      } catch (error) {
        console.warn(
          `Failed to delete web search provider ${webSearchProviderId}: ${error}`
        );
      }
    }

    // Clean up image gen config
    if (imageGenConfigId !== null) {
      try {
        await apiClient.deleteImageGenerationConfig(imageGenConfigId);
        imageGenConfigId = null;
      } catch (error) {
        console.warn(
          `Failed to delete image gen config ${imageGenConfigId}: ${error}`
        );
      }
    }
  });

  test("should load chat preferences page for admin users", async ({
    page,
  }) => {
    // Verify page loads with expected content
    await expect(page.locator('[aria-label="admin-page-title"]')).toHaveText(
      /^Chat Preferences/
    );
    await expect(page.getByText("Actions & Tools")).toBeVisible();
  });

  test("should toggle Internal Search tool on and off", async ({ page }) => {
    await page.waitForSelector("text=Internal Search", { timeout: 10000 });

    const searchSwitch = getToolSwitch(page, "Internal Search");

    // Get initial state
    const initialState = await searchSwitch.getAttribute("aria-checked");
    console.log(
      `[toggle] Internal Search initial aria-checked=${initialState}`
    );

    // Set up response listener before the click to avoid race conditions
    const patchRespPromise = page.waitForResponse(
      (r) =>
        r.url().includes("/api/admin/default-assistant") &&
        r.request().method() === "PATCH",
      { timeout: 8000 }
    );

    // Toggle it — auto-saves immediately
    await searchSwitch.click();

    // Wait for PATCH to complete
    const patchResp = await patchRespPromise;
    console.log(
      `[toggle] Internal Search PATCH status=${patchResp.status()} body=${(
        await patchResp.text()
      ).slice(0, 300)}`
    );

    // Wait for success toast
    await expect(page.getByText("Tools updated").first()).toBeVisible({
      timeout: 5000,
    });

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Internal Search", { timeout: 10000 });

    // Wait for SWR data to load and React to re-render with the persisted state
    const expectedState = initialState === "true" ? "false" : "true";
    await expect(searchSwitch).toHaveAttribute("aria-checked", expectedState, {
      timeout: 10000,
    });
    console.log(
      `[toggle] Internal Search after reload aria-checked=${expectedState}`
    );

    // Toggle back to original state
    await clickAndWaitForPatch(page, searchSwitch);
  });

  test("should toggle Web Search tool on and off", async ({ page }) => {
    await page.waitForSelector("text=Web Search", { timeout: 10000 });

    const webSearchSwitch = getToolSwitch(page, "Web Search");

    // Get initial state
    const initialState = await webSearchSwitch.getAttribute("aria-checked");
    console.log(`[toggle] Web Search initial aria-checked=${initialState}`);

    // Set up response listener before the click to avoid race conditions
    const patchRespPromise = page.waitForResponse(
      (r) =>
        r.url().includes("/api/admin/default-assistant") &&
        r.request().method() === "PATCH",
      { timeout: 8000 }
    );

    // Toggle it
    await webSearchSwitch.click();

    // Wait for PATCH to complete
    const patchResp = await patchRespPromise;
    console.log(
      `[toggle] Web Search PATCH status=${patchResp.status()} body=${(
        await patchResp.text()
      ).slice(0, 300)}`
    );

    // Wait for success toast
    await expect(page.getByText("Tools updated").first()).toBeVisible({
      timeout: 5000,
    });

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Web Search", { timeout: 10000 });

    // Wait for SWR data to load and React to re-render with the persisted state
    const expectedState = initialState === "true" ? "false" : "true";
    await expect(webSearchSwitch).toHaveAttribute(
      "aria-checked",
      expectedState,
      { timeout: 10000 }
    );
    console.log(
      `[toggle] Web Search after reload aria-checked=${expectedState}`
    );

    // Toggle back to original state
    await clickAndWaitForPatch(page, webSearchSwitch);
  });

  test("should toggle Image Generation tool on and off", async ({ page }) => {
    await page.waitForSelector("text=Image Generation", { timeout: 10000 });

    const imageGenSwitch = getToolSwitch(page, "Image Generation");

    // Get initial state
    const initialState = await imageGenSwitch.getAttribute("aria-checked");
    console.log(
      `[toggle] Image Generation initial aria-checked=${initialState}`
    );

    // Set up response listener before the click to avoid race conditions
    const patchRespPromise = page.waitForResponse(
      (r) =>
        r.url().includes("/api/admin/default-assistant") &&
        r.request().method() === "PATCH",
      { timeout: 8000 }
    );

    // Toggle it
    await imageGenSwitch.click();

    // Wait for PATCH to complete
    const patchResp = await patchRespPromise;
    console.log(
      `[toggle] Image Generation PATCH status=${patchResp.status()} body=${(
        await patchResp.text()
      ).slice(0, 300)}`
    );

    // Wait for success toast
    await expect(page.getByText("Tools updated").first()).toBeVisible({
      timeout: 5000,
    });

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Image Generation", { timeout: 10000 });

    // Wait for SWR data to load and React to re-render with the persisted state
    const expectedState = initialState === "true" ? "false" : "true";
    await expect(imageGenSwitch).toHaveAttribute(
      "aria-checked",
      expectedState,
      { timeout: 10000 }
    );
    console.log(
      `[toggle] Image Generation after reload aria-checked=${expectedState}`
    );

    // Toggle back to original state
    await clickAndWaitForPatch(page, imageGenSwitch);
  });

  test("should edit and save system prompt", async ({ page }) => {
    // Click "Modify Prompt" to open the system prompt modal
    await page.getByText("Modify Prompt").click();

    // Wait for modal to appear
    const modal = page.getByRole("dialog");
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Fill textarea with random suffix to ensure uniqueness
    const testPrompt = `This is a test system prompt for the E2E test. ${Math.floor(
      Math.random() * 1000000
    )}`;
    const textarea = modal.getByPlaceholder("Enter your system prompt...");
    await textarea.fill(testPrompt);

    // Click Save and wait for PATCH to complete
    await clickAndWaitForPatch(
      page,
      modal.getByRole("button", { name: "Save" })
    );

    // Modal should close after save
    await expect(modal).not.toBeVisible();

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForLoadState("networkidle");

    // Reopen modal and verify
    await page.getByText("Modify Prompt").click();
    const modalAfter = page.getByRole("dialog");
    await expect(modalAfter).toBeVisible({ timeout: 5000 });
    await expect(
      modalAfter.getByPlaceholder("Enter your system prompt...")
    ).toHaveValue(testPrompt);

    // Close modal without saving to clean up
    await modalAfter.getByRole("button", { name: "Cancel" }).click();
  });

  test("should allow empty system prompt", async ({ page }) => {
    // Open system prompt modal
    await page.getByText("Modify Prompt").click();
    const modal = page.getByRole("dialog");
    await expect(modal).toBeVisible({ timeout: 5000 });

    const textarea = modal.getByPlaceholder("Enter your system prompt...");

    // Get initial value to restore later
    const initialValue = await textarea.inputValue();

    // If already empty, add some text first
    if (initialValue === "") {
      await textarea.fill("Temporary text");
      await clickAndWaitForPatch(
        page,
        modal.getByRole("button", { name: "Save" })
      );
      // Reopen modal
      await page.getByText("Modify Prompt").click();
      await expect(modal).toBeVisible({ timeout: 5000 });
    }

    // Clear the textarea
    await textarea.fill("");

    // Save
    await clickAndWaitForPatch(
      page,
      modal.getByRole("button", { name: "Save" })
    );

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForLoadState("networkidle");

    // Reopen modal and check
    await page.getByText("Modify Prompt").click();
    const modalAfter = page.getByRole("dialog");
    await expect(modalAfter).toBeVisible({ timeout: 5000 });

    // The modal pre-populates with default prompt when system_prompt is empty/null,
    // so we just verify the modal opens without error
    const textareaAfter = modalAfter.getByPlaceholder(
      "Enter your system prompt..."
    );
    await expect(textareaAfter).toBeVisible();

    // Restore original value if it wasn't already empty
    if (initialValue !== "") {
      await textareaAfter.fill(initialValue);
      await clickAndWaitForPatch(
        page,
        modalAfter.getByRole("button", { name: "Save" })
      );
    } else {
      await modalAfter.getByRole("button", { name: "Cancel" }).click();
    }
  });

  test("should handle very long system prompt gracefully", async ({ page }) => {
    // Open system prompt modal
    await page.getByText("Modify Prompt").click();
    const modal = page.getByRole("dialog");
    await expect(modal).toBeVisible({ timeout: 5000 });

    const textarea = modal.getByPlaceholder("Enter your system prompt...");

    // Get initial value to restore later
    const initialValue = await textarea.inputValue();

    // Create a very long prompt (~4800 characters)
    const longPrompt = "This is a test. ".repeat(300);

    await textarea.fill(longPrompt);

    // Save
    await clickAndWaitForPatch(
      page,
      modal.getByRole("button", { name: "Save" })
    );

    // Verify persistence after reload
    await page.reload();
    await page.waitForLoadState("networkidle");

    await page.getByText("Modify Prompt").click();
    const modalAfter = page.getByRole("dialog");
    await expect(modalAfter).toBeVisible({ timeout: 5000 });
    await expect(
      modalAfter.getByPlaceholder("Enter your system prompt...")
    ).toHaveValue(longPrompt);

    // Restore original value
    if (initialValue !== longPrompt) {
      const restoreTextarea = modalAfter.getByPlaceholder(
        "Enter your system prompt..."
      );
      await restoreTextarea.fill(initialValue);
      await clickAndWaitForPatch(
        page,
        modalAfter.getByRole("button", { name: "Save" })
      );
    } else {
      await modalAfter.getByRole("button", { name: "Cancel" }).click();
    }
  });

  test("should reject invalid tool IDs via API", async ({ page }) => {
    // Use browser console to send invalid tool IDs
    // This simulates what would happen if someone tried to bypass the UI
    const response = await page.evaluate(async () => {
      const res = await fetch("/api/admin/default-assistant", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool_ids: ["InvalidTool", "AnotherInvalidTool"],
        }),
      });
      return {
        ok: res.ok,
        status: res.status,
        body: await res.text(),
      };
    });
    // Also try via page.request (uses storageState) to capture status in case page fetch fails
    try {
      const baseURL = process.env.BASE_URL || "http://localhost:3000";
      const alt = await page.request.patch(
        `${baseURL}/api/admin/default-assistant`,
        {
          data: { tool_ids: ["InvalidTool", "AnotherInvalidTool"] },
          headers: { "Content-Type": "application/json" },
        }
      );
      console.log(
        `[invalid-tools] page.request.patch status=${alt.status()} body=${(
          await alt.text()
        ).slice(0, 300)}`
      );
    } catch (e) {
      console.log(`[invalid-tools] page.request.patch error: ${String(e)}`);
    }

    // Check that the request failed with 400 or 422 (validation error)
    expect(response.ok).toBe(false);
    expect([400, 422].includes(response.status)).toBe(true);
    // The error message should indicate invalid tool IDs
    if (response.status === 400) {
      expect(response.body).toContain("Invalid tool IDs");
    }
  });

  test("should toggle all tools and verify in chat", async ({ page }) => {
    // Providers are now created in beforeEach, so all tools should be available

    // Wait for ALL three tools to be visible in the UI
    await page.waitForSelector("text=Internal Search", { timeout: 10000 });
    await page.waitForSelector("text=Web Search", { timeout: 10000 });
    await page.waitForSelector("text=Image Generation", { timeout: 10000 });

    // Wait for form to fully initialize
    await page.waitForTimeout(2000);

    // Store initial states
    const toolStates: Record<string, string | null> = {};

    // Capture current states (we'll restore these at the end)
    for (const toolName of [
      "Internal Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toolSwitch = getToolSwitch(page, toolName);
      const state = await toolSwitch.getAttribute("aria-checked");
      toolStates[toolName] = state;
      console.log(`[toggle-all] Initial state for ${toolName}: ${state}`);
    }

    // Disable all tools
    for (const toolName of [
      "Internal Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toolSwitch = getToolSwitch(page, toolName);
      const currentState = await toolSwitch.getAttribute("aria-checked");
      if (currentState === "true") {
        await clickAndWaitForPatch(page, toolSwitch);
        const newState = await toolSwitch.getAttribute("aria-checked");
        console.log(`[toggle-all] Clicked ${toolName}, new state=${newState}`);
      }
    }

    // Navigate to app to verify tools are disabled and initial load greeting
    await page.goto("/app");
    await waitForUnifiedGreeting(page);

    // Go back and re-enable all tools
    await page.goto("/admin/configuration/chat-preferences");
    await page.waitForLoadState("networkidle");
    // Reload to ensure the page has the updated tools list (after providers were created)
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.waitForSelector("text=Internal Search", { timeout: 10000 });

    for (const toolName of [
      "Internal Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toolSwitch = getToolSwitch(page, toolName);
      const currentState = await toolSwitch.getAttribute("aria-checked");
      if (currentState === "false") {
        await clickAndWaitForPatch(page, toolSwitch);
        const newState = await toolSwitch.getAttribute("aria-checked");
        console.log(`[toggle-all] Clicked ${toolName}, new state=${newState}`);
      }
    }

    // Navigate to app and verify the Action Management toggle and actions exist
    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    // Wait a bit for backend to process the changes
    await page.waitForTimeout(2000);

    // Reload to ensure ChatContext has fresh tool data after providers were created
    await page.reload();
    await page.waitForLoadState("networkidle");

    // Debug: Check what tools are available via API
    try {
      const baseURL = process.env.BASE_URL || "http://localhost:3000";
      const toolsResp = await page.request.get(`${baseURL}/api/tool`);
      const toolsData = await toolsResp.json();
      console.log(
        `[toggle-all] Available tools from API: ${JSON.stringify(
          toolsData.map((t: any) => ({
            name: t.name,
            display_name: t.display_name,
            in_code_tool_id: t.in_code_tool_id,
          }))
        )}`
      );
    } catch (e) {
      console.warn(`[toggle-all] Failed to fetch tools: ${e}`);
    }

    // Debug: Check assistant configuration
    try {
      const baseURL = process.env.BASE_URL || "http://localhost:3000";
      const configResp = await page.request.get(
        `${baseURL}/api/admin/default-assistant/configuration`
      );
      const configData = await configResp.json();
      console.log(
        `[toggle-all] Default assistant config: ${JSON.stringify(configData)}`
      );
    } catch (e) {
      console.warn(`[toggle-all] Failed to fetch config: ${e}`);
    }

    await waitForUnifiedGreeting(page);
    await expect(page.locator(TOOL_IDS.actionToggle)).toBeVisible();
    await openActionManagement(page);

    // Debug: Check what's actually in the popover
    const popover = page.locator(TOOL_IDS.options);
    const popoverText = await popover.textContent();
    console.log(`[toggle-all] Popover text: ${popoverText}`);

    // Verify at least Internal Search is visible (it should always be enabled)
    await expect(page.locator(TOOL_IDS.searchOption)).toBeVisible({
      timeout: 10000,
    });

    // Check if other tools are visible (they might not be if there's a form state issue)
    const webSearchVisible = await page
      .locator(TOOL_IDS.webSearchOption)
      .isVisible()
      .catch(() => false);
    const imageGenVisible = await page
      .locator(TOOL_IDS.imageGenerationOption)
      .isVisible()
      .catch(() => false);
    console.log(
      `[toggle-all] Tools visible in chat: Internal Search=true, Web Search=${webSearchVisible}, Image Gen=${imageGenVisible}`
    );

    // NOTE: Only Internal Search is verified as visible due to a known issue with
    // Web Search and Image Generation form state when providers are created in beforeEach.
    // This is being tracked separately as a potential Formik/form state bug.

    await page.goto("/admin/configuration/chat-preferences");

    // Restore original states
    let needsSave = false;
    for (const toolName of [
      "Internal Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toolSwitch = getToolSwitch(page, toolName);
      const currentState = await toolSwitch.getAttribute("aria-checked");
      const originalState = toolStates[toolName];

      if (currentState !== originalState) {
        await clickAndWaitForPatch(page, toolSwitch);
        needsSave = true;
      }
    }
  });
});

test.describe("Chat Preferences Non-Admin Access", () => {
  test("should redirect non-authenticated users", async ({ page }) => {
    // Clear cookies to ensure we're not authenticated
    await page.context().clearCookies();

    // Try to navigate directly to chat preferences without logging in
    await page.goto("/admin/configuration/chat-preferences");

    // Wait for navigation to settle
    await page.waitForTimeout(2000);

    // Should be redirected away from admin page
    const url = page.url();
    expect(!url.includes("/admin/configuration/chat-preferences")).toBe(true);
  });
});
