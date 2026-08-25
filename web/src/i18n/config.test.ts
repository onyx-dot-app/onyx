import { SUPPORTED_LOCALES } from "@/i18n/config";

describe("SUPPORTED_LOCALES", () => {
  it("matches the backend SupportedLanguage enum", () => {
    // Pin the locale list that mirrors the backend `SupportedLanguage` enum.
    // backend/tests/unit/onyx/db/test_supported_language.py pins the same
    // list on the backend side. If this test fails, update both places
    // together.
    expect([...SUPPORTED_LOCALES]).toEqual(["en", "es", "pt", "fr", "de"]);
  });
});
