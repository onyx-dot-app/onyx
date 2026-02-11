/**
 * E2E Test: Personal Access Token (PAT) Management
 * Tests complete user flow: login → create → authenticate → delete
 */
import { test, expect } from "@playwright/test";
import { loginAsRandomUser } from "../utils/auth";

test("PAT Complete Workflow", async ({ page }, testInfo) => {
  // Skip in admin project - we test with fresh user auth
  test.skip(
    testInfo.project.name === "admin",
    "Test requires clean user auth state"
  );

  await page.context().clearCookies();
  const { email } = await loginAsRandomUser(page);

  await page.goto("/app");
  await page.waitForLoadState("networkidle");

  // Click on user dropdown and open settings (same pattern as other tests)
  await page.locator("#onyx-user-dropdown").click();
  await page.getByText("User Settings").first().click();

  // Wait for settings modal to appear (first page has "Full Name" section)
  await expect(page.getByText("Full Name")).toBeVisible();

  await page
    .locator('a[href="/app/settings/accounts-access"]')
    .click({ force: true });

  // Wait for PAT page to load (button is unique to the PAT section)
  await expect(page.locator('button:has-text("New Access Token")')).toBeVisible(
    {
      timeout: 10000,
    }
  );

  await page.locator('button:has-text("New Access Token")').first().click();

  const tokenName = `E2E Test Token ${Date.now()}`;
  const nameInput = page
    .locator('input[placeholder*="Name your token"]')
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

  await page.locator('button:has-text("Create Token")').first().click();

  const tokenDisplay = page
    .locator("code")
    .filter({ hasText: "onyx_pat_" })
    .first();
  await tokenDisplay.waitFor({ state: "visible", timeout: 5000 });

  const tokenValue = await tokenDisplay.textContent();
  expect(tokenValue).toContain("onyx_pat_");

  // Grant clipboard permissions before copying
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);

  // Copy the newly created token (button is inside .code-copy-button)
  await page.locator(".code-copy-button button").click();

  // Wait a moment for clipboard to be written and verify
  await page.waitForTimeout(500);
  const clipboardText = await page.evaluate(() =>
    navigator.clipboard.readText()
  );
  expect(clipboardText).toBe(tokenValue);

  await page.locator('button:has-text("Done")').first().click();
  await expect(page.getByText(tokenName).first()).toBeVisible({
    timeout: 5000,
  });

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

  const confirmButton = page.locator('button:has-text("Revoke")').first();
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

  await page.goto("/app");
  await page.waitForLoadState("networkidle");

  // Click on user dropdown and open settings (same pattern as other tests)
  await page.locator("#onyx-user-dropdown").click();
  await page.getByText("User Settings").first().click();

  // Wait for settings modal to appear (first page has "Full Name" section)
  await expect(page.getByText("Full Name")).toBeVisible();

  await page
    .locator('a[href="/app/settings/accounts-access"]')
    .click({ force: true });

  // Wait for PAT page to load (button is unique to the PAT section)
  await expect(page.locator('button:has-text("New Access Token")')).toBeVisible(
    {
      timeout: 10000,
    }
  );

  const tokens = [
    { name: `Token 1 - ${Date.now()}`, expiration: "7 days" },
    { name: `Token 2 - ${Date.now() + 1}`, expiration: "30 days" },
    { name: `Token 3 - ${Date.now() + 2}`, expiration: "No expiration" },
  ];

  for (const token of tokens) {
    // Click "New Access Token" button to open the modal
    await page.locator('button:has-text("New Access Token")').first().click();

    // Fill in the token name
    const nameInput = page
      .locator('input[placeholder*="Name your token"]')
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

    // Create the token
    await page.locator('button:has-text("Create Token")').first().click();

    // Wait for token to be created (code block with token appears)
    await page
      .locator("code")
      .filter({ hasText: "onyx_pat_" })
      .first()
      .waitFor({ state: "visible", timeout: 5000 });

    // Close the modal by clicking "Done"
    await page.locator('button:has-text("Done")').first().click();

    // Wait for token to appear in the list
    await expect(page.getByText(token.name).first()).toBeVisible({
      timeout: 5000,
    });
  }

  // Verify all tokens are visible in the list
  for (const token of tokens) {
    await expect(page.getByText(token.name).first()).toBeVisible();
  }

  // Delete the second token using its aria-label
  const deleteButton = page.locator(
    `button[aria-label="Delete token ${tokens[1]!.name}"]`
  );
  await deleteButton.click();

  // Click "Revoke" to confirm deletion
  const confirmButton = page.locator('button:has-text("Revoke")').first();
  await confirmButton.waitFor({ state: "visible", timeout: 3000 });
  await confirmButton.click();

  // Wait for the modal to close
  await expect(confirmButton).not.toBeVisible({ timeout: 3000 });

  // Now verify the deleted token is no longer in the list
  await expect(page.getByText(tokens[1]!.name)).not.toBeVisible({
    timeout: 5000,
  });

  // Verify the other two tokens are still visible
  await expect(page.getByText(tokens[0]!.name).first()).toBeVisible();
  await expect(page.getByText(tokens[2]!.name).first()).toBeVisible();
});
