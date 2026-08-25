import { expect, test } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";

// Uses a fresh random user: changing the language mutates the user row, and
// doing that to the shared admin fixture would leak a non-English UI into
// concurrently running specs.
test("language picker switches the UI locale and persists", async ({
  page,
}) => {
  await loginAsRandomUser(page);

  await page.goto("/app/settings/general");

  // The picker lists languages by endonym, so its trigger text is
  // locale-independent and safe to target in any UI language.
  const languageSelect = page
    .getByRole("combobox")
    .filter({ hasText: "English" });
  await expect(languageSelect).toBeVisible();
  await languageSelect.click();
  await page.getByRole("option", { name: "Español" }).click();

  // router.refresh() re-renders the server layout with the new locale.
  await expect(page.locator("html")).toHaveAttribute("lang", "es");
  await expect(page.getByText("Apariencia").first()).toBeVisible();

  // The cookie and DB row both carry the preference across a full reload.
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "es");
  await expect(page.getByText("Apariencia").first()).toBeVisible();

  // Switch back, again via the locale-independent endonym.
  const languageSelectSpanish = page
    .getByRole("combobox")
    .filter({ hasText: "Español" });
  await languageSelectSpanish.click();
  await page.getByRole("option", { name: "English", exact: true }).click();

  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByText("Appearance").first()).toBeVisible();
});
