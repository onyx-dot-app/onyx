/**
 * E2E Tests: SCIM Token Management
 *
 * Tests the full lifecycle of SCIM tokens — generation, clipboard copy,
 * file download, and regeneration with confirmation.
 */

import { test, expect, gotoScimPage } from "./fixtures";

test.describe("SCIM Token Management", () => {
  test("generate token, copy, and download", async ({
    adminPage,
    mockTokenEndpoint: _mockTokenEndpoint,
  }) => {
    await gotoScimPage(adminPage);

    // No token yet — click generate
    await adminPage
      .getByRole("button", { name: "Generate SCIM Token" })
      .click();

    // Token modal opens
    await expect(
      adminPage.getByText("Save this key before continuing")
    ).toBeVisible({ timeout: 10000 });

    // Grab the raw token from the textarea
    const textarea = adminPage.locator("textarea");
    await textarea.waitFor({ state: "visible" });
    const tokenValue = await textarea.inputValue();
    expect(tokenValue).toContain("scim_test_token_");

    // Copy to clipboard
    await adminPage
      .context()
      .grantPermissions(["clipboard-read", "clipboard-write"]);
    await adminPage.getByRole("button", { name: "Copy Token" }).click();
    await expect(adminPage.getByText("Token copied to clipboard")).toBeVisible({
      timeout: 5000,
    });
    const clipboardText = await adminPage.evaluate(() =>
      navigator.clipboard.readText()
    );
    expect(clipboardText).toBe(tokenValue);

    // Download
    const downloadPromise = adminPage.waitForEvent("download");
    await adminPage.getByRole("button", { name: "Download" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/^onyx-scim-token-\d+\.txt$/);
  });

  test("regenerate token", async ({ adminPage, mockTokenEndpoint }) => {
    // Start with an existing token so the card shows "Regenerate"
    mockTokenEndpoint.seedToken();
    await gotoScimPage(adminPage);

    // Click regenerate on the card
    await adminPage.getByRole("button", { name: "Regenerate Token" }).click();

    // Confirmation modal appears
    await expect(adminPage.getByText("Regenerate SCIM Token")).toBeVisible();
    await expect(
      adminPage.getByText("Your current SCIM token will be revoked")
    ).toBeVisible();

    // Confirm via the danger button inside the dialog
    const dialog = adminPage.locator('[role="dialog"]');
    await dialog.getByRole("button", { name: "Regenerate Token" }).click();

    // Token display modal replaces the confirmation modal
    await expect(
      adminPage.getByText("Save this key before continuing")
    ).toBeVisible({ timeout: 10000 });

    const textarea = adminPage.locator("textarea");
    await textarea.waitFor({ state: "visible" });
    const tokenValue = await textarea.inputValue();
    expect(tokenValue).toContain("scim_test_token_");
  });
});
