import { test, expect } from "@chromatic-com/playwright";
import { Page } from "@playwright/test";
import { loginAs } from "../../utils/auth";

// --- Locator Helper Functions ---
const getNameInput = (page: Page) => page.locator('input[name="name"]');
const getAuthorizationUrlInput = (page: Page) =>
  page.locator('input[name="authorization_url"]');
const getTokenUrlInput = (page: Page) =>
  page.locator('input[name="token_url"]');
const getClientIdInput = (page: Page) =>
  page.locator('input[name="client_id"]');
const getClientSecretInput = (page: Page) =>
  page.locator('input[name="client_secret"]');
const getScopesInput = (page: Page) => page.locator('input[name="scopes"]');
const getCreateSubmitButton = (page: Page) =>
  page.getByRole("button", { name: "Create", exact: true });
const getDefinitionTextarea = (page: Page) =>
  page.locator('textarea[name="definition"]');
const getAdvancedOptionsButton = (page: Page) =>
  page.getByRole("button", { name: "Advanced Options" });
const getOAuthConfigSelector = (page: Page) =>
  page.locator('[role="combobox"]');
const getCreateActionButton = (page: Page) =>
  page.getByRole("button", { name: "Create Action" });

// Simple OpenAPI schema for testing
const SIMPLE_OPENAPI_SCHEMA = `{
  "openapi": "3.0.0",
  "info": {
    "title": "Test API",
    "version": "1.0.0",
    "description": "A test API for OAuth tool selection"
  },
  "servers": [
    {
      "url": "https://api.example.com"
    }
  ],
  "paths": {
    "/test": {
      "get": {
        "operationId": "test_operation",
        "summary": "Test operation",
        "description": "A test operation",
        "responses": {
          "200": {
            "description": "Success"
          }
        }
      }
    }
  }
}`;

test("Tool OAuth Configuration: Creation, Selection, and Assistant Integration", async ({
  page,
}) => {
  await page.context().clearCookies();
  await loginAs(page, "admin");

  // --- Step 1: Navigate to Tool Creation Page ---
  const configName = `Test Tool OAuth ${Date.now()}`;
  const toolName = `Test API ${Date.now()}`; // Unique tool name for this test run
  const provider = "github";
  const authorizationUrl = "https://github.com/login/oauth/authorize";
  const tokenUrl = "https://github.com/login/oauth/access_token";
  const clientId = "test_client_id_456";
  const clientSecret = "test_client_secret_789";
  const scopes = "repo, user";

  // Create a unique OpenAPI schema with the unique tool name
  const uniqueOpenAPISchema = SIMPLE_OPENAPI_SCHEMA.replace(
    '"title": "Test API"',
    `"title": "${toolName}"`
  );

  await page.goto("http://localhost:3000/admin/actions/new");
  await page.waitForLoadState("networkidle");

  // Fill in the OpenAPI definition
  const definitionTextarea = getDefinitionTextarea(page);
  await definitionTextarea.fill(uniqueOpenAPISchema);

  // Trigger validation by blurring the textarea
  await definitionTextarea.blur();

  // Wait for validation to complete (debounced, can take a few seconds)
  // The "Available methods" section appears after successful validation
  await expect(page.getByText("Available methods")).toBeVisible({
    timeout: 15000,
  });

  // --- Step 3: Open Advanced Options and Create OAuth Config ---
  const advancedOptionsButton = getAdvancedOptionsButton(page);
  await advancedOptionsButton.scrollIntoViewIfNeeded();
  await advancedOptionsButton.click();

  // Wait for advanced options to be visible
  await page.waitForTimeout(500);

  // Verify OAuth Config Selector is visible
  await expect(page.getByText("OAuth Configuration:")).toBeVisible();

  // Click "New OAuth Configuration" button
  const createNewOAuthButton = page.getByRole("button", {
    name: "New OAuth Configuration",
  });
  await createNewOAuthButton.click();

  // Wait for the modal to appear
  await page.waitForSelector('input[name="name"]', { state: "visible" });

  // Fill in OAuth config details
  await getNameInput(page).fill(configName);
  await getAuthorizationUrlInput(page).fill(authorizationUrl);
  await getTokenUrlInput(page).fill(tokenUrl);
  await getClientIdInput(page).fill(clientId);
  await getClientSecretInput(page).fill(clientSecret);
  await getScopesInput(page).fill(scopes);

  // Submit the creation form
  await getCreateSubmitButton(page).click();

  // Wait for the modal to close and config to be created
  await page.waitForTimeout(2000);

  // Wait for the OAuth config selector to be visible and contain the new config
  const oauthSelector = getOAuthConfigSelector(page);
  await expect(oauthSelector).toBeVisible({ timeout: 5000 });

  // The selector should now show the newly created config
  // Give extra time for the async mutation and field value update
  await expect(oauthSelector).toContainText(configName, { timeout: 10000 });

  // Wait for the selection to be processed
  await page.waitForTimeout(500);

  // --- Step 4: Submit the Tool Creation ---
  const createActionButton = getCreateActionButton(page);
  await createActionButton.scrollIntoViewIfNeeded();
  await createActionButton.click();

  // Wait for redirection after tool creation
  await page.waitForURL("**/admin/actions**", { timeout: 10000 });

  // --- Step 5: Verify Tool Was Created with OAuth Config ---
  // We should be redirected to the actions list page
  await page.waitForLoadState("networkidle");

  // Verify we're on the actions page
  expect(page.url()).toContain("/admin/actions");

  // The tool should appear - look for our unique tool name
  await expect(page.getByText(toolName, { exact: false }).first()).toBeVisible({
    timeout: 20000,
  });

  // --- Step 6: Verify OAuth Config Persists in Edit Mode ---
  // Edit the tool we just created to verify the OAuth config is still selected
  // Find the row with our unique tool name and click the edit icon
  const toolRow = page.locator(`tr:has-text("${toolName}")`).first();
  await expect(toolRow).toBeVisible({ timeout: 5000 });

  // Look for the edit button/icon in the row (usually has an aria-label or is a button/link)
  // Try multiple selectors to find the edit button
  const editButton = toolRow
    .locator(
      'button[aria-label*="dit"], a[aria-label*="dit"], svg, [class*="edit"]'
    )
    .first();
  await editButton.click();

  // Wait for the edit page to load
  await page.waitForLoadState("networkidle", { timeout: 30000 });

  // Wait for the definition textarea to be visible (indicates page is loaded)
  await expect(getDefinitionTextarea(page)).toBeVisible({ timeout: 20000 });

  // Open advanced options
  const advancedOptionsButtonEdit = getAdvancedOptionsButton(page);
  await expect(advancedOptionsButtonEdit).toBeVisible({ timeout: 10000 });
  await advancedOptionsButtonEdit.scrollIntoViewIfNeeded();
  await advancedOptionsButtonEdit.click();
  await page.waitForTimeout(500);

  // Verify the OAuth config selector shows our created config
  const oauthSelectorEdit = getOAuthConfigSelector(page);
  await expect(oauthSelectorEdit).toBeVisible({ timeout: 5000 });
  await oauthSelectorEdit.scrollIntoViewIfNeeded();
  await expect(oauthSelectorEdit).toContainText(configName, { timeout: 5000 });

  // Test complete for steps 1-4! We've verified:
  // 1. OAuth config can be created from the tool editor
  // 2. The newly created config is automatically selected in the dropdown
  // 3. The tool is created with the OAuth config
  // 4. The OAuth config persists when editing the tool

  // --- Step 7: Create Assistant and Verify Tool Availability ---
  // Navigate to the assistant creation page
  await page.goto("http://localhost:3000/assistants/new");
  await page.waitForLoadState("networkidle");

  // Fill in basic assistant details
  const assistantName = `Test Assistant ${Date.now()}`;
  const assistantDescription = "Assistant with OAuth tool";
  const assistantInstructions = "Use the tool when needed";

  await page.locator('input[name="name"]').fill(assistantName);
  await page.locator('input[name="description"]').fill(assistantDescription);
  await page
    .locator('textarea[name="system_prompt"]')
    .fill(assistantInstructions);

  // Scroll down to the Actions section (tools are listed there)
  const actionsHeading = page.locator("text=Actions").first();
  await expect(actionsHeading).toBeVisible({ timeout: 10000 });
  await actionsHeading.scrollIntoViewIfNeeded();

  // Look for our tool in the list
  // The tool display_name is the tool name we created
  const toolLabel = page.locator(`label:has-text("${toolName}")`);
  await expect(toolLabel).toBeVisible({ timeout: 10000 });
  await toolLabel.scrollIntoViewIfNeeded();

  // Turn it on
  await toolLabel.click();

  // Submit the assistant creation form
  const createButton = page.locator('button[type="submit"]:has-text("Create")');
  await createButton.scrollIntoViewIfNeeded();
  await createButton.click();

  // Verify redirection to chat page with the new assistant ID
  await page.waitForURL(/.*\/chat\?assistantId=\d+.*/, { timeout: 10000 });
  const assistantUrl = page.url();
  const assistantIdMatch = assistantUrl.match(/assistantId=(\d+)/);
  expect(assistantIdMatch).toBeTruthy();

  // Test complete! We've verified:
  // 5. The tool with OAuth config is available in assistant creation
  // 6. The tool can be selected and the assistant can be created successfully
});
