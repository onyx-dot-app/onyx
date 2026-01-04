/**
 * E2E Test: Personal Access Token (PAT) Management
 * Tests complete user flow: login → create → authenticate → delete
 */
import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";

test("PAT Complete Workflow", async ({ page }, testInfo) => {
  // Skip in admin project - we test with fresh user auth
  test.skip(
    testInfo.project.name === "admin",
    "Test requires clean user auth state"
  );

  await page.context().clearCookies();
  const { email } = await loginAsRandomUser(page);

  await page.goto("/chat");
  await page.waitForLoadState("networkidle");

  // Click on user dropdown and open settings (same pattern as other tests)
  await page.locator("#onyx-user-dropdown").click();
  await page.getByText("User Settings").first().click();

  // Wait for settings modal to appear (first page has Theme section)
  await expect(page.locator("h3", { hasText: "Theme" })).toBeVisible();

  const accessTokensTab = page
    .locator("text=Access Tokens")
    .or(page.locator('button:has-text("Access Tokens")'))
    .first();
  await accessTokensTab.click();

  // Wait for PAT page to load by checking for the h2 heading
  await expect(
    page.locator("h2", { hasText: "Personal Access Tokens" })
  ).toBeVisible({
    timeout: 10000,
  });

  const tokenName = `E2E Test Token ${Date.now()}`;
  const nameInput = page
    .locator('input[placeholder*="Token name"]')
    .or(page.locator('input[aria-label="Token name"]'))
    .first();
  await nameInput.fill(tokenName);

  // Click the Radix UI combobox for expiration (not a select element)
  const expirationCombobox = page.locator(
    'button[role="combobox"][aria-label*="expiration"]'
  );
  if (await expirationCombobox.isVisible()) {
    await expirationCombobox.click();
    // Wait for dropdown and select 7 days option using role=option
    await page.getByRole("option", { name: "7 days" }).click();
  }

  const createButton = page.locator('button:has-text("Create Token")').first();
  await createButton.click();

  // Wait for token to appear in the list
  await expect(page.locator(`p:text-is("${tokenName}")`)).toBeVisible({
    timeout: 5000,
  });

  const tokenDisplay = page
    .locator('[data-testid="token-value"]')
    .or(page.locator("code").filter({ hasText: "onyx_pat_" }))
    .first();
  await tokenDisplay.waitFor({ state: "visible", timeout: 5000 });

  const tokenValue = await tokenDisplay.textContent();
  expect(tokenValue).toContain("onyx_pat_");

  // Grant clipboard permissions before copying
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);

  // Copy the newly created token
  const copyButton = page
    .locator('button[aria-label="Copy token to clipboard"]')
    .or(page.locator('button:has-text("Copy Token")'))
    .first();

  await copyButton.click();

  // Wait a moment for clipboard to be written and verify
  await page.waitForTimeout(500);
  const clipboardText = await page.evaluate(() =>
    navigator.clipboard.readText()
  );
  expect(clipboardText).toBe(tokenValue);

  // Test the PAT token works by making an API request in a new context (no session cookies)
  const testContext = await page.context().browser()!.newContext();
  const apiResponse = await testContext.request.get(
    "http://localhost:3000/api/me",
    {
      headers: {
        Authorization: `Bearer ${tokenValue}`,
      },
    }
  );
  expect(apiResponse.ok()).toBeTruthy();
  const userData = await apiResponse.json();
  expect(userData.email).toBe(email);
  await testContext.close();

  // Find and click the delete button using the aria-label with token name
  const deleteButton = page.locator(
    `button[aria-label="Delete token ${tokenName}"]`
  );
  await deleteButton.click();

  const confirmButton = page
    .locator('button:has-text("Delete")')
    .or(page.locator('button:has-text("Confirm")'))
    .last();
  await confirmButton.waitFor({ state: "visible", timeout: 3000 });
  await confirmButton.click();

  // Wait for the modal to close (it contains the token name in its text)
  await expect(confirmButton).not.toBeVisible({ timeout: 3000 });

  // Now verify the token is no longer in the list
  await expect(page.locator(`p:text-is("${tokenName}")`)).not.toBeVisible({
    timeout: 5000,
  });

  // Create a new context without cookies to test the revoked token
  const newContext = await page.context().browser()!.newContext();
  const revokedApiResponse = await newContext.request.get(
    "http://localhost:3000/api/me",
    {
      headers: {
        Authorization: `Bearer ${tokenValue}`,
      },
    }
  );
  await newContext.close();
  // Revoked tokens return 403 Forbidden (as per backend tests)
  expect(revokedApiResponse.status()).toBe(403);
});

test("PAT Multiple Tokens Management", async ({ page }, testInfo) => {
  // Skip in admin project - we test with fresh user auth
  test.skip(
    testInfo.project.name === "admin",
    "Test requires clean user auth state"
  );

  await page.context().clearCookies();
  await loginAsRandomUser(page);

  await page.goto("/chat");
  await page.waitForLoadState("networkidle");

  // Click on user dropdown and open settings (same pattern as other tests)
  await page.locator("#onyx-user-dropdown").click();
  await page.getByText("User Settings").first().click();

  // Wait for settings modal to appear (first page has Theme section)
  await expect(page.locator("h3", { hasText: "Theme" })).toBeVisible();

  const accessTokensTab = page
    .locator("text=Access Tokens")
    .or(page.locator('button:has-text("Access Tokens")'))
    .first();
  await accessTokensTab.click();

  // Wait for PAT page to load by checking for the h2 heading
  await expect(
    page.locator("h2", { hasText: "Personal Access Tokens" })
  ).toBeVisible({
    timeout: 10000,
  });

  const tokens = [
    { name: `Token 1 - ${Date.now()}`, expiration: "7 days" },
    { name: `Token 2 - ${Date.now() + 1}`, expiration: "30 days" },
    { name: `Token 3 - ${Date.now() + 2}`, expiration: "No expiration" },
  ];

  for (const token of tokens) {
    const nameInput = page
      .locator('input[placeholder*="Token name"]')
      .or(page.locator('input[aria-label="Token name"]'))
      .first();
    await nameInput.fill(token.name);

    // Click the Radix UI combobox for expiration (not a select element)
    const expirationCombobox = page.locator(
      'button[role="combobox"][aria-label*="expiration"]'
    );
    if (await expirationCombobox.isVisible()) {
      await expirationCombobox.click();
      // Wait for dropdown and select the option using role=option
      await page.getByRole("option", { name: token.expiration }).click();
    }

    const createButton = page
      .locator('button:has-text("Create Token")')
      .first();
    await createButton.click();

    // Wait for token to appear in the list
    await expect(page.locator(`p:text-is("${token.name}")`)).toBeVisible({
      timeout: 5000,
    });
    await page.waitForTimeout(500);
  }

  // Verify all tokens are visible
  for (const token of tokens) {
    await expect(page.locator(`p:text-is("${token.name}")`)).toBeVisible();
  }

  // Verify tokens are sorted by created_at DESC (newest first)
  // Get all token rows (divs that contain delete buttons with aria-label starting with "Delete token")
  const tokenRows = page.locator(
    'div.flex.items-center.justify-between:has(button[aria-label^="Delete token"])'
  );
  const firstTokenText = await tokenRows.first().textContent();
  expect(firstTokenText).toContain(tokens[2]!.name);

  // Delete the second token using its aria-label
  const deleteButton = page.locator(
    `button[aria-label="Delete token ${tokens[1]!.name}"]`
  );
  await deleteButton.click();

  const confirmButton = page
    .locator('button:has-text("Delete")')
    .or(page.locator('button:has-text("Confirm")'))
    .last();
  await confirmButton.waitFor({ state: "visible", timeout: 3000 });
  await confirmButton.click();

  // Wait for the modal to close (it contains the token name in its text)
  await expect(confirmButton).not.toBeVisible({ timeout: 3000 });

  // Now verify the deleted token is no longer in the list
  await expect(page.locator(`p:text-is("${tokens[1]!.name}")`)).not.toBeVisible(
    {
      timeout: 5000,
    }
  );

  // Verify the other two tokens are still visible
  await expect(page.locator(`p:text-is("${tokens[0]!.name}")`)).toBeVisible();
  await expect(page.locator(`p:text-is("${tokens[2]!.name}")`)).toBeVisible();
});
