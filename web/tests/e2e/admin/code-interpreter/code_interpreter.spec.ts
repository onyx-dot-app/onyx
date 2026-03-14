import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

const CODE_INTERPRETER_URL = "/admin/configuration/code-interpreter";
const API_STATUS_URL = "**/api/admin/code-interpreter";
const API_HEALTH_URL = "**/api/admin/code-interpreter/health";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Intercept the status (GET /) and health (GET /health) endpoints with the
 * given values so the page renders deterministically.
 *
 * Also handles PUT requests — by default they succeed (200). Pass
 * `putStatus` to simulate failures.
 */
async function mockCodeInterpreterApi(
  page: Page,
  opts: {
    enabled: boolean;
    connected: boolean;
    error?: string;
    putStatus?: number;
  }
) {
  const putStatus = opts.putStatus ?? 200;

  await page.route(API_HEALTH_URL, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        connected: opts.connected,
        error: opts.error ?? "",
      }),
    });
  });

  await page.route(API_STATUS_URL, async (route) => {
    if (route.request().method() === "PUT") {
      await route.fulfill({
        status: putStatus,
        contentType: "application/json",
        body:
          putStatus >= 400
            ? JSON.stringify({ detail: "Server Error" })
            : JSON.stringify(null),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: opts.enabled }),
      });
    }
  });
}

/**
 * The disconnect icon button is an icon-only opal Button whose tooltip text
 * is not exposed as an accessible name. Locate it by finding the first
 * icon-only button (no label span) inside the card area.
 */
function getDisconnectIconButton(page: Page) {
  return page
    .locator("button:has(.opal-button):not(:has(.opal-button-label))")
    .first();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Code Interpreter Admin Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("page loads with header and description", async ({ page }) => {
    await mockCodeInterpreterApi(page, { enabled: true, connected: true });
    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.locator('[aria-label="admin-page-title"]')).toHaveText(
      /^Code Interpreter/,
      { timeout: 10000 }
    );

    await expect(page.getByText("Built-in Python runtime")).toBeVisible();
  });

  test("shows Connected status when enabled and healthy", async ({ page }) => {
    await mockCodeInterpreterApi(page, { enabled: true, connected: true });
    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.getByText("Connected")).toBeVisible({ timeout: 10000 });
  });

  test("shows Connection Lost when enabled but unhealthy", async ({ page }) => {
    await mockCodeInterpreterApi(page, { enabled: true, connected: false });
    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.getByText("Connection Lost")).toBeVisible({
      timeout: 10000,
    });
  });

  test("shows Reconnect button when disabled", async ({ page }) => {
    await mockCodeInterpreterApi(page, { enabled: false, connected: false });
    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.getByRole("button", { name: "Reconnect" })).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText("(Disconnected)")).toBeVisible();
  });

  test("disconnect flow opens modal and sends PUT request", async ({
    page,
  }) => {
    await mockCodeInterpreterApi(page, { enabled: true, connected: true });
    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.getByText("Connected")).toBeVisible({ timeout: 10000 });

    // Click the disconnect icon button
    await getDisconnectIconButton(page).click();

    // Modal should appear
    await expect(page.getByText("Disconnect Code Interpreter")).toBeVisible();
    await expect(
      page.getByText("All running sessions connected to")
    ).toBeVisible();

    // Click the danger Disconnect button in the modal
    const modal = page.getByRole("dialog");
    await modal.getByRole("button", { name: "Disconnect" }).click();

    // Modal should close after successful disconnect
    await expect(page.getByText("Disconnect Code Interpreter")).not.toBeVisible(
      { timeout: 5000 }
    );
  });

  test("disconnect modal can be closed without disconnecting", async ({
    page,
  }) => {
    await mockCodeInterpreterApi(page, { enabled: true, connected: true });
    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.getByText("Connected")).toBeVisible({ timeout: 10000 });

    // Open modal
    await getDisconnectIconButton(page).click();
    await expect(page.getByText("Disconnect Code Interpreter")).toBeVisible();

    // Close modal via Cancel button
    const modal = page.getByRole("dialog");
    await modal.getByRole("button", { name: "Cancel" }).click();

    // Modal should be gone, page still shows Connected
    await expect(
      page.getByText("Disconnect Code Interpreter")
    ).not.toBeVisible();
    await expect(page.getByText("Connected")).toBeVisible();
  });

  test("reconnect flow sends PUT with enabled=true", async ({ page }) => {
    await mockCodeInterpreterApi(page, { enabled: false, connected: false });
    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.getByRole("button", { name: "Reconnect" })).toBeVisible({
      timeout: 10000,
    });

    // Intercept the PUT and verify the payload
    const putPromise = page.waitForRequest(
      (req) =>
        req.url().includes("/api/admin/code-interpreter") &&
        req.method() === "PUT"
    );

    await page.getByRole("button", { name: "Reconnect" }).click();

    const putReq = await putPromise;
    expect(putReq.postDataJSON()).toEqual({ enabled: true });
  });

  test("shows Checking... while reconnect is in progress", async ({ page }) => {
    // Use a single route handler that delays PUT responses
    await page.route(API_HEALTH_URL, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ connected: false, error: "" }),
      });
    });

    await page.route(API_STATUS_URL, async (route) => {
      if (route.request().method() === "PUT") {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(null),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ enabled: false }),
        });
      }
    });

    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.getByRole("button", { name: "Reconnect" })).toBeVisible({
      timeout: 10000,
    });

    await page.getByRole("button", { name: "Reconnect" }).click();

    // Should show Checking... while the request is in flight
    await expect(page.getByText("Checking...")).toBeVisible({ timeout: 3000 });
  });

  test("shows error toast when disconnect fails", async ({ page }) => {
    await mockCodeInterpreterApi(page, {
      enabled: true,
      connected: true,
      putStatus: 500,
    });
    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.getByText("Connected")).toBeVisible({ timeout: 10000 });

    // Open modal and click disconnect
    await getDisconnectIconButton(page).click();
    const modal = page.getByRole("dialog");
    await modal.getByRole("button", { name: "Disconnect" }).click();

    // Error toast should appear
    await expect(
      page.getByText("Failed to disconnect Code Interpreter")
    ).toBeVisible({ timeout: 5000 });
  });

  test("shows error toast when reconnect fails", async ({ page }) => {
    await mockCodeInterpreterApi(page, {
      enabled: false,
      connected: false,
      putStatus: 500,
    });
    await page.goto(CODE_INTERPRETER_URL);

    await expect(page.getByRole("button", { name: "Reconnect" })).toBeVisible({
      timeout: 10000,
    });

    await page.getByRole("button", { name: "Reconnect" }).click();

    // Error toast should appear
    await expect(
      page.getByText("Failed to reconnect Code Interpreter")
    ).toBeVisible({ timeout: 5000 });

    // Reconnect button should reappear (not stuck in Checking...)
    await expect(page.getByRole("button", { name: "Reconnect" })).toBeVisible({
      timeout: 5000,
    });
  });

  test("shows error popover on hover over unhealthy status icon", async ({
    page,
  }) => {
    const errorMessage = "Sandbox runtime crashed unexpectedly";
    await mockCodeInterpreterApi(page, {
      enabled: true,
      connected: true,
      error: errorMessage,
    });
    await page.goto(CODE_INTERPRETER_URL);

    // Wait for the Unhealthy status to render
    const statusText = page.getByText("Unhealthy");
    await expect(statusText).toBeVisible({ timeout: 10000 });

    // Error popover should not be visible initially
    await expect(page.getByText("Code Interpreter Error")).not.toBeVisible();

    // Hover over the status icon — sibling of the status label
    const statusIcon = statusText.locator("..").locator(".cursor-pointer");
    await statusIcon.hover();

    // Error popover should appear with the title and error description
    await expect(page.getByText("Code Interpreter Error")).toBeVisible({
      timeout: 3000,
    });
    await expect(page.getByText(errorMessage)).toBeVisible();

    // Move mouse away — error popover should disappear
    await page.mouse.move(0, 0);
    await expect(page.getByText("Code Interpreter Error")).not.toBeVisible({
      timeout: 3000,
    });
  });

  test("shows error popover on hover over connection lost status icon", async ({
    page,
  }) => {
    const errorMessage = "Failed to reach code interpreter service";
    await mockCodeInterpreterApi(page, {
      enabled: true,
      connected: false,
      error: errorMessage,
    });
    await page.goto(CODE_INTERPRETER_URL);

    // Wait for the Connection Lost status to render
    const statusText = page.getByText("Connection Lost");
    await expect(statusText).toBeVisible({ timeout: 10000 });

    // Hover over the status icon — sibling of the status label
    const statusIcon = statusText.locator("..").locator(".cursor-pointer");
    await statusIcon.hover();

    // Error popover should show the connection lost title and error
    await expect(page.getByText("Connection Lost Error")).toBeVisible({
      timeout: 3000,
    });
    await expect(page.getByText(errorMessage)).toBeVisible();
  });

  test("does not show error popover on hover when healthy", async ({
    page,
  }) => {
    await mockCodeInterpreterApi(page, {
      enabled: true,
      connected: true,
    });
    await page.goto(CODE_INTERPRETER_URL);

    const statusText = page.getByText("Connected");
    await expect(statusText).toBeVisible({ timeout: 10000 });

    // The status icon wrapper should not have cursor-pointer when healthy
    await expect(
      statusText.locator("..").locator(".cursor-pointer")
    ).toHaveCount(0);
  });
});
