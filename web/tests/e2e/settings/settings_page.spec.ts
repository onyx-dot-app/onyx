import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import {
  expectScreenshot,
  expectElementScreenshot,
} from "@tests/e2e/utils/visualRegression";

const SETTINGS_TABS = [
  { name: "General", path: "/app/settings/general" },
  { name: "Chat Preferences", path: "/app/settings/chat-preferences" },
  { name: "Accounts & Access", path: "/app/settings/accounts-access" },
  { name: "Connectors", path: "/app/settings/connectors" },
] as const;

for (const theme of THEMES) {
  test.describe(`Settings Page Visual Regression (${theme} mode)`, () => {
    test.beforeEach(async ({ page }, testInfo) => {
      await page.context().clearCookies();
      await setThemeBeforeNavigation(page, theme);
      await loginAsWorkerUser(page, testInfo.workerIndex);
    });

    for (const tab of SETTINGS_TABS) {
      test(`${tab.name} tab renders correctly`, async ({ page }) => {
        await page.goto(tab.path);
        await page.waitForLoadState("networkidle");

        await expect(page.getByText("Settings")).toBeVisible({
          timeout: 10000,
        });

        await expectScreenshot(page, {
          name: `settings-${tab.name
            .toLowerCase()
            .replace(/\s+&\s+/g, "-")
            .replace(/\s+/g, "-")}-${theme}`,
        });
      });
    }
  });
}

test.describe("Settings Page - General", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
  });

  test("should display Profile section with name and role fields", async ({
    page,
  }) => {
    await page.goto("/app/settings/general");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Profile")).toBeVisible();
    await expect(page.getByText("Full Name")).toBeVisible();
    await expect(page.getByPlaceholder("Your name")).toBeVisible();
    await expect(page.getByText("Work Role")).toBeVisible();
    await expect(page.getByPlaceholder("Your role")).toBeVisible();
  });

  test("should display Appearance section with color mode and chat background", async ({
    page,
  }) => {
    await page.goto("/app/settings/general");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Appearance")).toBeVisible();
    await expect(page.getByText("Color Mode")).toBeVisible();
    await expect(page.getByText("Chat Background")).toBeVisible();
  });

  test("should update name field and persist on blur", async ({ page }) => {
    await page.goto("/app/settings/general");
    await page.waitForLoadState("networkidle");

    const nameInput = page.getByPlaceholder("Your name");
    await nameInput.click();
    await nameInput.fill("E2E Test Name");
    await nameInput.blur();

    const saveResponse = page.waitForResponse(
      (resp) =>
        resp.url().includes("/api/user/personalization") &&
        resp.request().method() === "PATCH"
    );
    await saveResponse;

    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.getByPlaceholder("Your name")).toHaveValue(
      "E2E Test Name"
    );

    await nameInput.click();
    await nameInput.fill("worker");
    await nameInput.blur();
    await page.waitForResponse(
      (resp) =>
        resp.url().includes("/api/user/personalization") &&
        resp.request().method() === "PATCH"
    );
  });

  test("should update role field and persist on blur", async ({ page }) => {
    await page.goto("/app/settings/general");
    await page.waitForLoadState("networkidle");

    const roleInput = page.getByPlaceholder("Your role");
    await roleInput.click();
    await roleInput.fill("E2E Tester");
    await roleInput.blur();

    const saveResponse = page.waitForResponse(
      (resp) =>
        resp.url().includes("/api/user/personalization") &&
        resp.request().method() === "PATCH"
    );
    await saveResponse;

    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.getByPlaceholder("Your role")).toHaveValue("E2E Tester");

    await roleInput.click();
    await roleInput.fill("");
    await roleInput.blur();
    await page.waitForResponse(
      (resp) =>
        resp.url().includes("/api/user/personalization") &&
        resp.request().method() === "PATCH"
    );
  });

  test("should show delete all chats confirmation modal", async ({ page }) => {
    await page.goto("/app/settings/general");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Danger Zone")).toBeVisible();

    const deleteButton = page.getByRole("button", {
      name: "Delete All Chats",
    });
    await expect(deleteButton).toBeVisible();
    await deleteButton.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByText(
        "All your chat sessions and history will be permanently deleted."
      )
    ).toBeVisible();

    await expectElementScreenshot(dialog, {
      name: "settings-delete-all-chats-modal",
    });

    const cancelButton = dialog.getByRole("button", { name: "Cancel" });
    await cancelButton.click();
    await expect(dialog).not.toBeVisible();
  });

  test("should navigate between settings tabs via sidebar", async ({
    page,
  }) => {
    await page.goto("/app/settings/general");
    await page.waitForLoadState("networkidle");

    await page.getByRole("link", { name: "Chat Preferences" }).click();
    await expect(page).toHaveURL(/\/app\/settings\/chat-preferences/);
    await expect(page.getByText("Default Model")).toBeVisible();

    await page.getByRole("link", { name: "Connectors" }).click();
    await expect(page).toHaveURL(/\/app\/settings\/connectors/);
    await expect(page.getByText("Connectors")).toBeVisible();

    await page.getByRole("link", { name: "General" }).click();
    await expect(page).toHaveURL(/\/app\/settings\/general/);
    await expect(page.getByText("Profile")).toBeVisible();
  });
});

test.describe("Settings Page - Chat Preferences", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
  });

  test("should display chats section with default model and auto-scroll", async ({
    page,
  }) => {
    await page.goto("/app/settings/chat-preferences");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Default Model")).toBeVisible();
    await expect(page.getByText("Chat Auto-scroll")).toBeVisible();
  });

  test("should display personal preferences textarea", async ({ page }) => {
    await page.goto("/app/settings/chat-preferences");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Personal Preferences")).toBeVisible();
    await expect(
      page.getByPlaceholder(
        "Describe how you want the system to behave and the tone it should use."
      )
    ).toBeVisible();
  });

  test("should display memory toggles", async ({ page }) => {
    await page.goto("/app/settings/chat-preferences");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Memory")).toBeVisible();
    await expect(page.getByText("Reference Stored Memories")).toBeVisible();
    await expect(page.getByText("Update Memories")).toBeVisible();
  });

  test("should display prompt shortcuts section", async ({ page }) => {
    await page.goto("/app/settings/chat-preferences");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Prompt Shortcuts")).toBeVisible();
    await expect(page.getByText("Use Prompt Shortcuts")).toBeVisible();
  });
});

test.describe("Settings Page - Accounts & Access", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
  });

  test("should display email address", async ({ page }) => {
    await page.goto("/app/settings/accounts-access");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Accounts")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Email")).toBeVisible();
  });

  test("should display change password button and open modal", async ({
    page,
  }) => {
    await page.goto("/app/settings/accounts-access");
    await page.waitForLoadState("networkidle");

    const changePasswordButton = page.getByRole("button", {
      name: "Change Password",
    });

    if (await changePasswordButton.isVisible()) {
      await changePasswordButton.click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText("Change Password")).toBeVisible();
      await expect(dialog.getByText("Current Password")).toBeVisible();
      await expect(dialog.getByText("New Password")).toBeVisible();
      await expect(dialog.getByText("Confirm New Password")).toBeVisible();

      await expectElementScreenshot(dialog, {
        name: "settings-change-password-modal",
      });

      const cancelButton = dialog.getByRole("button", { name: "Cancel" });
      await cancelButton.click();
      await expect(dialog).not.toBeVisible();
    }
  });

  test("should display access tokens section", async ({ page }) => {
    await page.goto("/app/settings/accounts-access");
    await page.waitForLoadState("networkidle");

    const tokensTitle = page.getByText("Access Tokens");
    if (await tokensTitle.isVisible()) {
      await expect(
        page.getByRole("button", { name: "New Access Token" })
      ).toBeVisible();
    }
  });

  test("should open create access token modal", async ({ page }) => {
    await page.goto("/app/settings/accounts-access");
    await page.waitForLoadState("networkidle");

    const createButton = page.getByRole("button", {
      name: "New Access Token",
    });
    if (await createButton.isVisible()) {
      await createButton.click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText("Create Access Token")).toBeVisible();
      await expect(dialog.getByPlaceholder("Name your token")).toBeVisible();

      await expectElementScreenshot(dialog, {
        name: "settings-create-token-modal",
      });

      const cancelButton = dialog.getByRole("button", { name: "Cancel" });
      await cancelButton.click();
      await expect(dialog).not.toBeVisible();
    }
  });
});
