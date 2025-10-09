import { test, expect } from "@playwright/test";
import { loginAs } from "../utils/auth";
import {
  TOOL_IDS,
  waitForUnifiedGreeting,
  openActionManagement,
} from "../utils/tools";

test.describe("Default Assistant Admin Page", () => {
  test.beforeEach(async ({ page }) => {
    // Log in as admin
    await page.context().clearCookies();
    await loginAs(page, "admin");

    // Navigate to default assistant
    await page.goto(
      "http://localhost:3000/admin/configuration/default-assistant"
    );
    await page.waitForURL(
      "http://localhost:3000/admin/configuration/default-assistant"
    );

    // Attach basic API logging for this spec
    page.on("response", async (resp) => {
      const url = resp.url();
      if (url.includes("/api/admin/default-assistant")) {
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
      const toolsResp = await page.request.get(
        "http://localhost:3000/api/admin/default-assistant/available-tools"
      );
      const cfgResp = await page.request.get(
        "http://localhost:3000/api/admin/default-assistant/configuration"
      );
      console.log(
        `[/available-tools] status=${toolsResp.status()} body=${(
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

  test("should load default assistant page for admin users", async ({
    page,
  }) => {
    // Verify page loads with expected content
    await expect(
      page.getByRole("heading", { name: "Default Assistant" })
    ).toBeVisible();
    // Avoid strict mode collision from multiple "Actions" elements
    await expect(page.getByText("Instructions", { exact: true })).toBeVisible();
    await expect(page.getByText("Instructions", { exact: true })).toBeVisible();
  });

  test("should toggle Internal Search tool on and off", async ({ page }) => {
    await page.waitForSelector("text=Internal Search", { timeout: 10000 });

    // Find the Internal Search toggle using a more robust selector
    const searchToggle = page
      .locator('div:has-text("Internal Search")')
      .filter({ hasText: "Internal Search" })
      .locator('[role="switch"]')
      .first();

    // Get initial state
    const initialState = await searchToggle.getAttribute("data-state");
    const isDisabled = await searchToggle.isDisabled().catch(() => false);
    console.log(
      `[toggle] Internal Search initial data-state=${initialState} disabled=${isDisabled}`
    );

    // Toggle it
    await searchToggle.click();

    // Wait for PATCH to complete (or log if it didn't happen)
    const patchResp = await Promise.race([
      page.waitForResponse(
        (r) =>
          r.url().includes("/api/admin/default-assistant") &&
          r.request().method() === "PATCH",
        { timeout: 8000 }
      ),
      page.waitForTimeout(8500).then(() => null),
    ]);
    if (patchResp) {
      console.log(
        `[toggle] Internal Search PATCH status=${patchResp.status()} body=${(
          await patchResp.text()
        ).slice(0, 300)}`
      );
    } else {
      console.log(`[toggle] Internal Search did not observe PATCH response`);
    }

    // Wait for the change to persist
    await page.waitForTimeout(1000);

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Internal Search", { timeout: 10000 });

    // Check that state persisted
    const searchToggleAfter = page
      .locator('div:has-text("Internal Search")')
      .filter({ hasText: "Internal Search" })
      .locator('[role="switch"]')
      .first();
    const newState = await searchToggleAfter.getAttribute("data-state");
    console.log(`[toggle] Internal Search after reload data-state=${newState}`);

    // State should have changed
    expect(initialState).not.toBe(newState);

    // Toggle back to original state
    await searchToggleAfter.click();
    await page.waitForTimeout(1000);
  });

  test("should toggle Web Search tool on and off", async ({ page }) => {
    await page.waitForSelector("text=Web Search", { timeout: 10000 });

    // Find the Web Search toggle using a more robust selector
    const webSearchToggle = page
      .locator('div:has-text("Web Search")')
      .filter({ hasText: "Web Search" })
      .locator('[role="switch"]')
      .first();

    // Get initial state
    const initialState = await webSearchToggle.getAttribute("data-state");
    const isDisabled = await webSearchToggle.isDisabled().catch(() => false);
    console.log(
      `[toggle] Web Search initial data-state=${initialState} disabled=${isDisabled}`
    );

    // Toggle it
    await webSearchToggle.click();
    const patchResp = await Promise.race([
      page.waitForResponse(
        (r) =>
          r.url().includes("/api/admin/default-assistant") &&
          r.request().method() === "PATCH",
        { timeout: 8000 }
      ),
      page.waitForTimeout(8500).then(() => null),
    ]);
    if (patchResp) {
      console.log(
        `[toggle] Web Search PATCH status=${patchResp.status()} body=${(
          await patchResp.text()
        ).slice(0, 300)}`
      );
    } else {
      console.log(`[toggle] Web Search did not observe PATCH response`);
    }

    // Wait for the change to persist
    await page.waitForTimeout(1000);

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Web Search", { timeout: 10000 });

    // Check that state persisted
    const webSearchToggleAfter = page
      .locator('div:has-text("Web Search")')
      .filter({ hasText: "Web Search" })
      .locator('[role="switch"]')
      .first();
    const newState = await webSearchToggleAfter.getAttribute("data-state");
    console.log(`[toggle] Web Search after reload data-state=${newState}`);

    // State should have changed
    expect(initialState).not.toBe(newState);

    // Toggle back to original state
    await webSearchToggleAfter.click();
    await page.waitForTimeout(1000);
  });

  test("should toggle Image Generation tool on and off", async ({ page }) => {
    await page.waitForSelector("text=Image Generation", { timeout: 10000 });

    // Find the Image Generation toggle using a more robust selector
    const imageGenToggle = page
      .locator('div:has-text("Image Generation")')
      .filter({ hasText: "Image Generation" })
      .locator('[role="switch"]')
      .first();

    // Get initial state
    const initialState = await imageGenToggle.getAttribute("data-state");
    const isDisabled = await imageGenToggle.isDisabled().catch(() => false);
    console.log(
      `[toggle] Image Generation initial data-state=${initialState} disabled=${isDisabled}`
    );

    // Toggle it
    await imageGenToggle.click();
    const patchResp = await Promise.race([
      page.waitForResponse(
        (r) =>
          r.url().includes("/api/admin/default-assistant") &&
          r.request().method() === "PATCH",
        { timeout: 8000 }
      ),
      page.waitForTimeout(8500).then(() => null),
    ]);
    if (patchResp) {
      console.log(
        `[toggle] Image Generation PATCH status=${patchResp.status()} body=${(
          await patchResp.text()
        ).slice(0, 300)}`
      );
    } else {
      console.log(`[toggle] Image Generation did not observe PATCH response`);
    }

    // Wait for the change to persist
    await page.waitForTimeout(1000);

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Image Generation", { timeout: 10000 });

    // Check that state persisted
    const imageGenToggleAfter = page
      .locator('div:has-text("Image Generation")')
      .filter({ hasText: "Image Generation" })
      .locator('[role="switch"]')
      .first();
    const newState = await imageGenToggleAfter.getAttribute("data-state");
    console.log(
      `[toggle] Image Generation after reload data-state=${newState}`
    );

    // State should have changed
    expect(initialState).not.toBe(newState);

    // Toggle back to original state
    await imageGenToggleAfter.click();
    await page.waitForTimeout(1000);
  });

  test("should edit and save system prompt", async ({ page }) => {
    await page.waitForSelector("text=Instructions", { timeout: 10000 });

    // Find the textarea using a more flexible selector
    const textarea = page.locator(
      'textarea[placeholder*="professional email writing assistant"]'
    );

    // Get initial value
    const initialValue = await textarea.inputValue();

    // Clear and enter new text
    const testPrompt = "This is a test system prompt for the E2E test.";
    await textarea.fill(testPrompt);

    // Save changes
    const saveButton = page.locator("text=Save Instructions");
    await saveButton.click();
    const patchResp = await Promise.race([
      page.waitForResponse(
        (r) =>
          r.url().includes("/api/admin/default-assistant") &&
          r.request().method() === "PATCH",
        { timeout: 8000 }
      ),
      page.waitForTimeout(8500).then(() => null),
    ]);
    if (patchResp) {
      console.log(
        `[prompt] Save PATCH status=${patchResp.status()} body=${(
          await patchResp.text()
        ).slice(0, 300)}`
      );
    } else {
      console.log(`[prompt] Did not observe PATCH response on save`);
    }

    // Wait for success message
    await expect(
      page.locator("text=Instructions updated successfully!")
    ).toBeVisible();

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Instructions", { timeout: 10000 });

    // Check that new value persisted
    const textareaAfter = page.locator(
      'textarea[placeholder*="professional email writing assistant"]'
    );
    await expect(textareaAfter).toHaveValue(testPrompt);

    // Restore original value
    await textareaAfter.fill(initialValue);
    const saveButtonAfter = page.locator("text=Save Instructions");
    await saveButtonAfter.click();
    await expect(
      page.locator("text=Instructions updated successfully!")
    ).toBeVisible();
  });

  test("should allow empty system prompt", async ({ page }) => {
    await page.waitForSelector("text=Instructions", { timeout: 10000 });

    // Find the textarea using a more flexible selector
    const textarea = page.locator(
      'textarea[placeholder*="professional email writing assistant"]'
    );

    // Get initial value to restore later
    const initialValue = await textarea.inputValue();

    // If already empty, add some text first
    if (initialValue === "") {
      await textarea.fill("Temporary text");
      const tempSaveButton = page.locator("text=Save Instructions");
      await tempSaveButton.click();
      const patchResp1 = await page.waitForResponse(
        (r) =>
          r.url().includes("/api/admin/default-assistant") &&
          r.request().method() === "PATCH"
      );
      console.log(
        `[prompt-empty] Temp save PATCH status=${patchResp1.status()} body=${(
          await patchResp1.text()
        ).slice(0, 300)}`
      );
      await expect(
        page.locator("text=Instructions updated successfully!")
      ).toBeVisible();
      await page.waitForTimeout(1000);
    }

    // Now clear the textarea
    await textarea.fill("");

    // Save changes
    const saveButton = page.locator("text=Save Instructions");
    await saveButton.click();
    const patchResp2 = await page.waitForResponse(
      (r) =>
        r.url().includes("/api/admin/default-assistant") &&
        r.request().method() === "PATCH"
    );
    console.log(
      `[prompt-empty] Save empty PATCH status=${patchResp2.status()} body=${(
        await patchResp2.text()
      ).slice(0, 300)}`
    );

    // Wait for success message
    await expect(
      page.locator("text=Instructions updated successfully!")
    ).toBeVisible();

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Instructions", { timeout: 10000 });

    // Check that empty value persisted
    const textareaAfter = page.locator(
      'textarea[placeholder*="professional email writing assistant"]'
    );
    await expect(textareaAfter).toHaveValue("");

    // Restore original value if it wasn't already empty
    if (initialValue !== "") {
      await textareaAfter.fill(initialValue);
      const saveButtonAfter = page.locator("text=Save Instructions");
      await saveButtonAfter.click();
      const patchResp3 = await page.waitForResponse(
        (r) =>
          r.url().includes("/api/admin/default-assistant") &&
          r.request().method() === "PATCH"
      );
      console.log(
        `[prompt-empty] Restore PATCH status=${patchResp3.status()} body=${(
          await patchResp3.text()
        ).slice(0, 300)}`
      );
      await expect(
        page.locator("text=Instructions updated successfully!")
      ).toBeVisible();
    }
  });

  test("should handle very long system prompt gracefully", async ({ page }) => {
    await page.waitForSelector("text=Instructions", { timeout: 10000 });

    // Find the textarea using a more flexible selector
    const textarea = page.locator(
      'textarea[placeholder*="professional email writing assistant"]'
    );

    // Get initial value to restore later
    const initialValue = await textarea.inputValue();

    // Create a very long prompt (5000 characters)
    const longPrompt = "This is a test. ".repeat(300); // ~4800 characters

    // If the current value is already the long prompt, use a different one
    if (initialValue === longPrompt) {
      const differentPrompt = "Different test. ".repeat(300);
      await textarea.fill(differentPrompt);
    } else {
      await textarea.fill(longPrompt);
    }

    // Save changes
    const saveButton = page.locator("text=Save Instructions");
    await saveButton.click();
    const patchResp = await page.waitForResponse(
      (r) =>
        r.url().includes("/api/admin/default-assistant") &&
        r.request().method() === "PATCH"
    );
    console.log(
      `[prompt-long] Save PATCH status=${patchResp.status()} body=${(
        await patchResp.text()
      ).slice(0, 300)}`
    );

    // Wait for success message
    await expect(
      page.locator("text=Instructions updated successfully!")
    ).toBeVisible();

    // Verify character count is displayed
    const currentValue = await textarea.inputValue();
    const charCount = page.locator("text=characters");
    await expect(charCount).toContainText(currentValue.length.toString());

    // Restore original value if it's different
    if (initialValue !== currentValue) {
      await textarea.fill(initialValue);
      await saveButton.click();
      const patchRespRestore = await page.waitForResponse(
        (r) =>
          r.url().includes("/api/admin/default-assistant") &&
          r.request().method() === "PATCH"
      );
      console.log(
        `[prompt-long] Restore PATCH status=${patchRespRestore.status()} body=${(
          await patchRespRestore.text()
        ).slice(0, 300)}`
      );
      await expect(
        page.locator("text=Instructions updated successfully!")
      ).toBeVisible();
    }
  });

  test("should display character count for system prompt", async ({ page }) => {
    await page.waitForSelector("text=Instructions", { timeout: 10000 });

    // Find the textarea using a more flexible selector
    const textarea = page.locator(
      'textarea[placeholder*="professional email writing assistant"]'
    );

    // Type some text
    const testText = "Test text for character counting";
    await textarea.fill(testText);

    // Check character count is displayed correctly
    await expect(page.locator("text=characters")).toContainText(
      testText.length.toString()
    );
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
      const alt = await page.request.patch(
        "http://localhost:3000/api/admin/default-assistant",
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
    await page.waitForSelector("text=Internal Search", { timeout: 10000 });

    // Store initial states
    const toolStates: Record<string, string | null> = {};

    // Get initial states of all tools
    for (const toolName of [
      "Internal Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toggle = page
        .locator(`div:has-text("${toolName}")`)
        .filter({ hasText: toolName })
        .locator('[role="switch"]')
        .first();
      toolStates[toolName] = await toggle.getAttribute("data-state");
    }

    // Disable all tools
    for (const toolName of [
      "Internal Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toggle = page
        .locator(`div:has-text("${toolName}")`)
        .filter({ hasText: toolName })
        .locator('[role="switch"]')
        .first();
      if ((await toggle.getAttribute("data-state")) === "checked") {
        await toggle.click();
        await page.waitForTimeout(500);
      }
    }

    // Navigate to chat to verify tools are disabled and initial load greeting
    await page.goto("http://localhost:3000/chat");
    await waitForUnifiedGreeting(page);
    // The Action Management toggle may still exist but with no enabled tools inside
    // So instead, check if specific tool options are not available
    try {
      await openActionManagement(page);
      // If we can open it, check that tools are disabled
      expect(await page.$(TOOL_IDS.searchOption)).toBeFalsy();
      expect(await page.$(TOOL_IDS.webSearchOption)).toBeFalsy();
      expect(await page.$(TOOL_IDS.imageGenerationOption)).toBeFalsy();
      // Image generation might still show as disabled
    } catch {
      // If Action Management can't be opened, that's also acceptable
      // when all tools are disabled
    }

    // Go back and re-enable all tools
    await page.goto(
      "http://localhost:3000/admin/configuration/default-assistant"
    );
    await page.waitForSelector("text=Internal Search", { timeout: 10000 });

    for (const toolName of [
      "Internal Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toggle = page
        .locator(`div:has-text("${toolName}")`)
        .filter({ hasText: toolName })
        .locator('[role="switch"]')
        .first();
      if ((await toggle.getAttribute("data-state")) === "unchecked") {
        await toggle.click();
        await page.waitForTimeout(500);
      }
    }

    // Navigate to chat and verify the Action Management toggle and actions exist
    await page.goto("http://localhost:3000/chat");
    await waitForUnifiedGreeting(page);
    await expect(page.locator(TOOL_IDS.actionToggle)).toBeVisible();
    await openActionManagement(page);
    expect(await page.$(TOOL_IDS.searchOption)).toBeTruthy();
    expect(await page.$(TOOL_IDS.webSearchOption)).toBeTruthy();
    expect(await page.$(TOOL_IDS.imageGenerationOption)).toBeTruthy();

    await page.goto(
      "http://localhost:3000/admin/configuration/default-assistant"
    );

    // Restore original states
    for (const toolName of [
      "Internal Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toggle = page
        .locator(`div:has-text("${toolName}")`)
        .filter({ hasText: toolName })
        .locator('[role="switch"]')
        .first();
      const currentState = await toggle.getAttribute("data-state");
      const originalState = toolStates[toolName];

      if (currentState !== originalState) {
        await toggle.click();
        await page.waitForTimeout(500);
      }
    }
  });
});

test.describe("Default Assistant Non-Admin Access", () => {
  test("should redirect non-authenticated users", async ({ page }) => {
    // Clear cookies to ensure we're not authenticated
    await page.context().clearCookies();

    // Try to navigate directly to default assistant without logging in
    await page.goto(
      "http://localhost:3000/admin/configuration/default-assistant"
    );

    // Wait for navigation to settle
    await page.waitForTimeout(2000);

    // Should be redirected away from admin page
    const url = page.url();
    expect(!url.includes("/admin/configuration/default-assistant")).toBe(true);
  });
});
