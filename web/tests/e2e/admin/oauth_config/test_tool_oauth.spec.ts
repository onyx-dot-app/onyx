import { test, expect } from "@chromatic-com/playwright";
import { Page } from "@playwright/test";
import { loginAs } from "../../utils/auth";

// --- Locator Helper Functions ---
const getNameInput = (page: Page) => page.locator('input[name="name"]');
const getProviderInput = (page: Page) => page.locator('input[name="provider"]');
const getAuthorizationUrlInput = (page: Page) =>
  page.locator('input[name="authorization_url"]');
const getTokenUrlInput = (page: Page) =>
  page.locator('input[name="token_url"]');
const getClientIdInput = (page: Page) =>
  page.locator('input[name="client_id"]');
const getClientSecretInput = (page: Page) =>
  page.locator('input[name="client_secret"]');
const getScopesInput = (page: Page) => page.locator('input[name="scopes"]');
const getCreateOAuthConfigButton = (page: Page) =>
  page.getByRole("button", { name: "Create OAuth Configuration" });
const getCreateSubmitButton = (page: Page) =>
  page.getByRole("button", { name: "Create", exact: true });
const getDefinitionTextarea = (page: Page) =>
  page.locator('textarea[name="definition"]');
const getAdvancedOptionsButton = (page: Page) =>
  page.getByRole("button", { name: "Advanced Options" });
const getOAuthConfigSelector = (page: Page) =>
  page
    .locator("text=OAuth Configuration:")
    .locator("..")
    .locator("..")
    .getByRole("button")
    .first();
const getPassthroughAuthCheckbox = (page: Page) =>
  page
    .locator('input[name="passthrough_auth"]')
    .or(page.locator("#passthrough_auth"));
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

test("Tool OAuth Selection and Passthrough Auth Disable", async ({ page }) => {
  await page.context().clearCookies();
  await loginAs(page, "admin");

  // --- Step 1: Navigate to Tool Creation Page ---
  const configName = `Test Tool OAuth ${Date.now()}`;
  const provider = "github";
  const authorizationUrl = "https://github.com/login/oauth/authorize";
  const tokenUrl = "https://github.com/login/oauth/access_token";
  const clientId = "test_client_id_456";
  const clientSecret = "test_client_secret_789";
  const scopes = "repo, user";

  await page.goto("http://localhost:3000/admin/actions/new");
  await page.waitForLoadState("networkidle");

  // Fill in the OpenAPI definition
  const definitionTextarea = getDefinitionTextarea(page);
  await definitionTextarea.fill(SIMPLE_OPENAPI_SCHEMA);

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

  // Click "Create New OAuth Config" button
  const createNewOAuthButton = page.getByRole("button", {
    name: "Create New OAuth Config",
  });
  await createNewOAuthButton.click();

  // Wait for the modal to appear
  await page.waitForSelector('input[name="name"]', { state: "visible" });

  // Fill in OAuth config details
  await getNameInput(page).fill(configName);
  await getProviderInput(page).fill(provider);
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
  await expect(oauthSelector).toContainText(configName, { timeout: 5000 });

  // Wait for the selection to be processed
  await page.waitForTimeout(500);

  // --- Step 4: Submit the Tool Creation ---
  const createActionButton = getCreateActionButton(page);
  await createActionButton.scrollIntoViewIfNeeded();
  await createActionButton.click();

  // Wait for redirection after tool creation
  await page.waitForURL("**/admin/actions", { timeout: 5000 });

  // --- Step 5: Verify Tool Was Created with OAuth Config ---
  // We should be redirected to the actions list page
  await page.waitForLoadState("networkidle");

  // Verify we're on the actions page
  expect(page.url()).toContain("/admin/actions");

  // The tool should appear in the list with the OAuth config
  // We can verify by checking if "test_operation" appears (the operation from our OpenAPI schema)
  await expect(page.getByText("test_operation").first()).toBeVisible();

  // --- Step 6: Verify OAuth Config Can Be Changed to None ---
  // Edit the tool we just created
  // Find the action row and click on it
  await page
    .locator('tr:has-text("test_operation")')
    .first()
    .locator("td")
    .first()
    .click();

  // Wait for the edit page to load
  await page.waitForLoadState("networkidle");

  // Open advanced options
  const advancedOptionsButtonEdit = getAdvancedOptionsButton(page);
  await advancedOptionsButtonEdit.scrollIntoViewIfNeeded();
  await advancedOptionsButtonEdit.click();
  await page.waitForTimeout(500);

  // Change OAuth config to "None"
  const oauthSelectorEdit = getOAuthConfigSelector(page);
  await oauthSelectorEdit.scrollIntoViewIfNeeded();

  // Click the selector to open the dropdown
  await oauthSelectorEdit.click();

  // Wait for the dropdown to appear and click "None"
  await page.getByRole("option", { name: "None" }).click();

  // Wait for the selection to be processed
  await page.waitForTimeout(500);

  // Now passthrough auth should be enabled (not disabled)
  const passthroughCheckboxEdit = getPassthroughAuthCheckbox(page);
  await passthroughCheckboxEdit.scrollIntoViewIfNeeded();

  // It should not be disabled anymore
  await expect(passthroughCheckboxEdit).not.toBeDisabled();
});
