import { test, expect } from "@chromatic-com/playwright";
import { Page } from "@playwright/test";
import { loginAs } from "../../utils/auth";

// --- Locator Helper Functions ---
const getAuthorizationUrlInput = (page: Page) =>
  page.locator('input[name="authorizationUrl"]');
const getTokenUrlInput = (page: Page) => page.locator('input[name="tokenUrl"]');
const getClientIdInput = (page: Page) => page.locator('input[name="clientId"]');
const getClientSecretInput = (page: Page) =>
  page.locator('input[name="clientSecret"]');
const getScopesInput = (page: Page) => page.locator('input[name="scopes"]');
const getConnectButton = (page: Page) =>
  page.getByRole("button", { name: "Connect" });
const getDefinitionTextarea = (page: Page) =>
  page.locator('textarea[name="definition"]');
const getAddActionButton = (page: Page) =>
  page.getByRole("button", { name: "Add Action" });
const getAddOpenAPIActionButton = (page: Page) =>
  page.getByRole("button", { name: "Add OpenAPI Action" });

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

  // --- Step 1: Navigate to OpenAPI Actions Page and Open Add Modal ---
  const toolName = `Test API ${Date.now()}`; // Unique tool name for this test run
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

  await page.goto("/admin/actions/open-api");
  await page.waitForLoadState("networkidle");

  // Click "Add OpenAPI Action" button to open modal
  const addOpenAPIActionButton = getAddOpenAPIActionButton(page);
  await addOpenAPIActionButton.click();

  // Wait for modal to appear
  await expect(
    page.getByRole("dialog", { name: "Add OpenAPI action" })
  ).toBeVisible({ timeout: 5000 });

  // Fill in the OpenAPI definition in the modal
  const definitionTextarea = getDefinitionTextarea(page);
  await definitionTextarea.fill(uniqueOpenAPISchema);

  // Wait for validation to complete (debounced, can take a few seconds)
  // The tool name appears in the modal after successful validation
  await expect(page.getByText(toolName)).toBeVisible({
    timeout: 15000,
  });

  // --- Step 2: Submit the OpenAPI Action Creation ---
  const addActionButton = getAddActionButton(page);
  await addActionButton.scrollIntoViewIfNeeded();
  await addActionButton.click();

  // --- Step 3: Configure OAuth in Authentication Modal ---
  // Wait for the authentication modal to appear
  await expect(page.getByText("Authentication Method")).toBeVisible({
    timeout: 5000,
  });

  // OAuth should be selected by default, fill in OAuth config details
  await getAuthorizationUrlInput(page).fill(authorizationUrl);
  await getTokenUrlInput(page).fill(tokenUrl);
  await getClientIdInput(page).fill(clientId);
  await getClientSecretInput(page).fill(clientSecret);
  await getScopesInput(page).fill(scopes);

  // Submit the authentication form
  const connectButton = getConnectButton(page);
  await connectButton.click();

  // Wait for authentication to complete and return to the actions list
  await page.waitForTimeout(2000);

  // --- Step 4: Verify Tool Was Created with OAuth Config ---
  // We should be on the OpenAPI actions page
  await page.waitForLoadState("networkidle");

  // Verify we're on the open-api page
  expect(page.url()).toContain("/admin/actions/open-api");

  // The tool should appear in the actions list - look for our unique tool name
  await expect(page.getByText(toolName, { exact: false }).first()).toBeVisible({
    timeout: 20000,
  });

  // --- Step 5: Verify OAuth Config Persists in Edit Mode ---
  // Find the action card with our tool and click the manage button
  const actionCard = page.locator(`[aria-label*="${toolName}"]`).first();
  await expect(actionCard).toBeVisible({ timeout: 5000 });

  // Click the manage button (gear icon) on the card
  const manageButton = actionCard
    .getByRole("button", { name: /manage/i })
    .or(actionCard.locator('button[aria-label*="anage"]'))
    .first();
  await manageButton.click();

  // Wait for the edit modal to appear
  const editDialog = page.getByRole("dialog", { name: "Edit OpenAPI action" });
  await expect(editDialog).toBeVisible({ timeout: 5000 });

  // Wait for the definition textarea to be visible (indicates modal is loaded)
  await expect(editDialog.locator('textarea[name="definition"]')).toBeVisible({
    timeout: 10000,
  });

  // Verify authentication status is shown (indicates OAuth is configured)
  await expect(editDialog.getByText("Authenticated & Enabled")).toBeVisible({
    timeout: 5000,
  });

  // Verify the "Edit Configs" button is visible (confirms OAuth config persists)
  const editConfigsButton = editDialog.getByRole("button", {
    name: "Edit Configs",
  });
  await expect(editConfigsButton).toBeVisible({ timeout: 5000 });

  // Close the modal
  const closeButton = page
    .locator('button[aria-label*="lose"]')
    .or(page.getByRole("button", { name: "Cancel" }))
    .first();
  await closeButton.click();

  // Wait for modal to close
  await page.waitForTimeout(500);

  // Test complete for steps 1-5! We've verified:
  // 1. OpenAPI action can be created via modal
  // 2. OAuth config is created and applied during action creation
  // 3. The tool is created and authenticated with the OAuth config
  // 4. The OAuth config persists when editing the tool

  // --- Step 6: Create Assistant and Verify Tool Availability ---
  // Navigate to the assistant creation page
  await page.goto("/chat/agents/create");
  await page.waitForLoadState("networkidle");

  // Fill in basic assistant details
  const assistantName = `Test Assistant ${Date.now()}`;
  const assistantDescription = "Assistant with OAuth tool";
  const assistantInstructions = "Use the tool when needed";

  await page.locator('input[name="name"]').fill(assistantName);
  await page.locator('textarea[name="description"]').fill(assistantDescription);
  await page
    .locator('textarea[name="instructions"]')
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
