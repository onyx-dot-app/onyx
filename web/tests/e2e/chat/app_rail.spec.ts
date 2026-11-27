import { expect, test } from "@playwright/test";

test.use({ storageState: "admin_auth.json" });

test("the rail switches windows and the sidebar follows", async ({ page }) => {
  await page.goto("/app");
  await expect(page.getByTestId("AppSidebar/new-session")).toBeVisible();

  await page.getByTestId("AppRail/customize").click();
  await expect(page).toHaveURL(/\/app\/customize\/skills$/);
  await expect(
    page.getByRole("link", { name: "Integrations", exact: true })
  ).toBeVisible();
  await expect(page.getByTestId("AppSidebar/new-session")).toBeHidden();

  await page.getByTestId("AppRail/agents").click();
  await expect(page).toHaveURL(/\/app\/agents$/);
  await expect(
    page.getByRole("link", { name: "Explore Agents", exact: true })
  ).toBeVisible();

  await page.getByTestId("AppRail/admin").click();
  await expect(page).toHaveURL(/\/admin\//);
  await expect(page.getByPlaceholder("Search...")).toBeVisible();

  await page.getByTestId("AppRail/chat").click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByTestId("AppSidebar/new-session")).toBeVisible();
});

test("folding hides the sidebar and keeps the rail", async ({ page }) => {
  await page.goto("/app");
  const newSession = page.getByTestId("AppSidebar/new-session");
  await expect(newSession).toBeVisible();

  await page.getByRole("button", { name: "Close Sidebar" }).click();
  await expect(newSession).toBeHidden();
  await expect(page.getByTestId("AppRail/customize")).toBeVisible();

  await page.getByRole("button", { name: "Open Sidebar" }).click();
  await expect(newSession).toBeVisible();
});
