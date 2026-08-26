import { test } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import { SettingsGeneralPage } from "@tests/e2e/pages/SettingsGeneralPage";

// Uses a fresh random user: changing the language mutates the user row, and
// doing that to the shared admin fixture would leak a non-English UI into
// concurrently running specs.
test("language picker switches the UI locale and persists", async ({
  page,
}) => {
  await loginAsRandomUser(page);

  const settingsPage = new SettingsGeneralPage(page);
  await settingsPage.goto();

  await settingsPage.switchLanguage("English", "Español");
  // router.refresh() re-renders the server layout with the new locale.
  await settingsPage.expectLocale("es", "Apariencia");

  // The cookie and DB row both carry the preference across a full reload.
  await settingsPage.reload();
  await settingsPage.expectLocale("es", "Apariencia");

  await settingsPage.switchLanguage("Español", "English");
  await settingsPage.expectLocale("en", "Appearance");
});
