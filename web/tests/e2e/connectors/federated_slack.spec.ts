import { test, expect } from "@chromatic-com/playwright";
import type { Page } from "@playwright/test";
import { loginAs, loginAsRandomUser } from "../utils/auth";

test.use({ storageState: "admin_auth.json" });

const SLACK_CLIENT_ID = process.env.SLACK_CLIENT_ID;
const SLACK_CLIENT_SECRET = process.env.SLACK_CLIENT_SECRET;

async function createFederatedSlackConnector(page: Page) {
  // Navigate to add connector page
  await page.goto("http://localhost:3000/admin/add-connector");
  await page.waitForLoadState("networkidle");

  // Click on Slack connector tile (specifically the one with "Logo Slack" text, not "Slack Bots")
  await page.getByRole("link", { name: "Logo Slack" }).first().click();
  await page.waitForLoadState("networkidle");

  if (!SLACK_CLIENT_ID || !SLACK_CLIENT_SECRET) {
    throw new Error("SLACK_CLIENT_ID and SLACK_CLIENT_SECRET must be set");
  }

  // Fill in the client ID and client secret
  await page.getByLabel(/client id/i).fill(SLACK_CLIENT_ID);
  await page.getByLabel(/client secret/i).fill(SLACK_CLIENT_SECRET);

  // Submit the form to create or update the federated connector
  const createOrUpdateButton = await page.getByRole("button", {
    name: /create|update/i,
  });
  await createOrUpdateButton.click();

  // Wait for success message or redirect
  await page.waitForTimeout(2000);
}

async function navigateToUserSettings(page: Page) {
  // Wait for any existing modals to close
  await page.waitForTimeout(1000);

  // Wait for potential modal backdrop to disappear
  await page
    .waitForSelector(".fixed.inset-0.bg-neutral-950\\/50", {
      state: "detached",
      timeout: 5000,
    })
    .catch(() => {});

  // Click on user dropdown/settings button
  await page.locator("#onyx-user-dropdown").click();

  // Click on settings option
  await page.getByText("User Settings").click();

  // Wait for settings modal to appear
  await expect(page.locator("h2", { hasText: "User Settings" })).toBeVisible();
}

async function openConnectorsTab(page: Page) {
  // Click on the Connectors tab in user settings
  await page.getByRole("button", { name: "Connectors" }).click();

  // Wait for connectors section to be visible
  // Allow multiple instances of "Connected Services" to be visible
  const connectedServicesLocators = page.getByText("Connected Services");
  await expect(connectedServicesLocators.first()).toBeVisible();
}

/**
 * Cleanup function to delete the federated Slack connector from the admin panel
 * This ensures test isolation by removing any test data created during the test
 */
async function deleteFederatedSlackConnector(page: Page) {
  // Navigate to admin indexing status page
  await page.goto("http://localhost:3000/admin/indexing/status");
  await page.waitForLoadState("networkidle");

  // Expand the Slack section first (summary row toggles open on click)
  const slackSummaryRow = page.locator("tr").filter({
    has: page.locator("text=/^\\s*Slack\\s*$/i"),
  });
  if ((await slackSummaryRow.count()) > 0) {
    await slackSummaryRow.first().click();
    // Wait a moment for rows to render
    await page.waitForTimeout(500);
  }

  // Look for the Slack federated connector row inside the expanded section
  // The federated connectors have a "Federated Access" badge
  const slackRow = page.locator("tr", { hasText: /federated access/i });

  // Check if the connector exists
  const rowCount = await slackRow.count();
  if (rowCount === 0) {
    // No federated Slack connector found, nothing to delete
    console.log("No federated Slack connector found to delete");
    return;
  }

  // Click on the row to navigate to the detail page
  await slackRow.first().click();
  await page.waitForLoadState("networkidle");

  // Look for and click the delete button
  // Open the Manage menu and click Delete
  const manageButton = page.getByRole("button", { name: /manage/i });
  await manageButton
    .waitFor({ state: "visible", timeout: 5000 })
    .catch(() => {});
  if (!(await manageButton.isVisible().catch(() => false))) {
    console.log("Manage button not visible; skipping delete");
    return;
  }
  await manageButton.click();
  // Wait for the dropdown menu to appear and settle (Radix animation)
  await page
    .getByRole("menu")
    .waitFor({ state: "visible", timeout: 3000 })
    .catch(() => {});
  await page.waitForTimeout(150);

  page.once("dialog", (dialog) => dialog.accept());
  const deleteMenuItem = page.getByRole("menuitem", { name: /^Delete$/ });
  await expect(deleteMenuItem).toBeVisible({ timeout: 5000 });
  await deleteMenuItem.click({ force: true });
  // Wait for deletion to complete and redirect
  await page.waitForURL("**/admin/indexing/status*", { timeout: 15000 });
  await page.waitForLoadState("networkidle");
}

// Causes other tests to fail for some reason???
// TODO (chris): fix this test
test.skip("Federated Slack Connector - Create, OAuth Modal, and User Settings Flow", async ({
  page,
}) => {
  try {
    // Setup: Clear cookies and log in as admin
    await page.context().clearCookies();
    await loginAs(page, "admin");

    // Create a federated Slack connector in admin panel
    await createFederatedSlackConnector(page);

    // Log in as a random user
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate back to main page and verify OAuth modal appears
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    // Check if the OAuth modal appears
    await expect(
      page.getByText(/improve answer quality by letting/i)
    ).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/slack/i)).toBeVisible();

    // Decline the OAuth connection
    await page.getByRole("button", { name: "Skip for now" }).click();

    // Wait for modal to disappear
    await expect(
      page.getByText(/improve answer quality by letting/i)
    ).not.toBeVisible();

    // Go to user settings and verify the connector appears
    await navigateToUserSettings(page);
    await openConnectorsTab(page);

    // Verify Slack connector appears in the federated connectors section
    await expect(page.getByText("Federated Connectors")).toBeVisible();
    await expect(page.getByText("Slack")).toBeVisible();
    await expect(page.getByText("Not connected")).toBeVisible();

    // Verify there's a Connect button available
    await expect(
      page.locator("button", { hasText: /^Connect$/ })
    ).toBeVisible();
  } finally {
    // Cleanup: Delete the federated Slack connector
    // Log back in as admin to delete the connector
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await deleteFederatedSlackConnector(page);
  }
});
