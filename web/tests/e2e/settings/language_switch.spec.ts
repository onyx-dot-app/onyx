import { test } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import { SettingsGeneralPage } from "@tests/e2e/pages/SettingsGeneralPage";

// One Latin-script locale and one CJK locale cover the two rendering paths
// (the CJK case also exercises the ja catalog and the <html lang> switch the
// :lang() line-breaking CSS keys off). marker is the locale's translation of
// settings.appearance.title, visible on the settings page.
const LOCALES = [
  { endonym: "Español", lang: "es", marker: "Apariencia" },
  { endonym: "日本語", lang: "ja", marker: "外観" },
] as const;

for (const { endonym, lang, marker } of LOCALES) {
  // Uses a fresh random user: changing the language mutates the user row, and
  // doing that to the shared admin fixture would leak a non-English UI into
  // concurrently running specs.
  test(`language picker switches the UI locale to ${lang} and persists`, async ({
    page,
  }) => {
    await loginAsRandomUser(page);

    const settingsPage = new SettingsGeneralPage(page);
    await settingsPage.goto();

    await settingsPage.switchLanguage("English", endonym);
    // router.refresh() re-renders the server layout with the new locale.
    await settingsPage.expectLocale(lang, marker);

    // The cookie and DB row both carry the preference across a full reload.
    await settingsPage.reload();
    await settingsPage.expectLocale(lang, marker);

    await settingsPage.switchLanguage(endonym, "English");
    await settingsPage.expectLocale("en", "Appearance");
  });
}
