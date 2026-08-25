import { SUPPORTED_LOCALES } from "@/i18n/config";

describe("SUPPORTED_LOCALES", () => {
  it("matches the backend SupportedLanguage enum", () => {
    // Pin the locale list that mirrors the backend `SupportedLanguage` enum
    // (backend/onyx/db/enums.py). If this test fails, update both places
    // together.
    expect([...SUPPORTED_LOCALES]).toEqual(["en", "es", "pt", "fr", "de"]);
  });
});
