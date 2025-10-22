import { test, expect } from "@chromatic-com/playwright";
import { Page } from "@playwright/test";
import { loginAs } from "../utils/auth";

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
const getCreateNewOAuthConfigButton = (page: Page) =>
  page.getByRole("button", { name: "Create New OAuth Config" });
const getCreateSubmitButton = (page: Page) =>
  page.getByRole("button", { name: "Create", exact: true });
const getAdvancedOptionsButton = (page: Page) =>
  page.getByRole("button", { name: "Advanced Options" });
const getDefinitionTextarea = (page: Page) =>
  page.locator('textarea[name="definition"]');

// Simple OpenAPI schema for testing
const SIMPLE_OPENAPI_SCHEMA = `{
  "openapi": "3.0.0",
  "info": {
    "title": "Test API",
    "version": "1.0.0"
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

test("OAuth Config Creation from Tool Editor", async ({ page }) => {
  await page.context().clearCookies();
  await loginAs(page, "admin");

  // --- Initial Values ---
  const configName = `Test OAuth Config ${Date.now()}`;
  const provider = "github";
  const authorizationUrl = "https://github.com/login/oauth/authorize";
  const tokenUrl = "https://github.com/login/oauth/access_token";
  const clientId = "test_client_id_123";
  const clientSecret = "test_client_secret_456";
  const scopes = "repo, user";

  // Navigate to the tool creation page
  await page.goto("http://localhost:3000/admin/actions/new");
  await page.waitForLoadState("networkidle");

  // Fill in a basic OpenAPI definition to enable form
  const definitionTextarea = getDefinitionTextarea(page);
  await definitionTextarea.fill(SIMPLE_OPENAPI_SCHEMA);
  await definitionTextarea.blur();

  // Wait for validation
  await expect(page.getByText("Available methods")).toBeVisible({
    timeout: 15000,
  });

  // Open Advanced Options
  const advancedOptionsButton = getAdvancedOptionsButton(page);
  await advancedOptionsButton.scrollIntoViewIfNeeded();
  await advancedOptionsButton.click();
  await page.waitForTimeout(500);

  // --- Create New OAuth Config ---
  await getCreateNewOAuthConfigButton(page).click();

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

  // Wait for the modal to close
  await page.waitForTimeout(1000);

  // Verify the OAuth config was created and selected in the dropdown
  const oauthSelector = page.locator('select[name="oauth_config_id"]');
  await oauthSelector.scrollIntoViewIfNeeded();

  // The newly created config should be automatically selected
  // Verify it appears in the dropdown with the format "ConfigName (provider)"
  const selectedOption = await oauthSelector
    .locator("option:checked")
    .textContent();
  expect(selectedOption).toContain(configName);
  expect(selectedOption).toContain(provider);

  // Verify that passthrough auth is disabled
  const passthroughCheckbox = page
    .locator('input[name="passthrough_auth"]')
    .or(page.locator("#passthrough_auth"));
  await passthroughCheckbox.scrollIntoViewIfNeeded();
  await expect(passthroughCheckbox).toBeDisabled();

  // Verify the tooltip message explaining why passthrough auth is disabled
  await expect(
    page.getByText(
      /Cannot enable passthrough auth when an OAuth configuration is selected/i
    )
  ).toBeVisible();
});
