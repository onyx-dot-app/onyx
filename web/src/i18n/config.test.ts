import {
  SUPPORTED_LOCALES,
  htmlDirForLocale,
  messageLocale,
  runtimeLocale,
} from "@/i18n/config";

describe("SUPPORTED_LOCALES", () => {
  it("matches the backend SupportedLanguage enum", () => {
    // Pin the locale list that mirrors the backend `SupportedLanguage` enum
    // (backend/onyx/db/enums.py). If this test fails, update both places
    // together.
    expect([...SUPPORTED_LOCALES]).toEqual([
      "en",
      "es",
      "pt",
      "fr",
      "de",
      "ja",
      "zh",
      "ko",
      "ar",
    ]);
  });
});

describe("runtime locale", () => {
  it("adds the Arabic-Indic numbering system to Arabic only", () => {
    expect(runtimeLocale("ar")).toBe("ar-u-nu-arab");
    for (const locale of SUPPORTED_LOCALES.filter((l) => l !== "ar")) {
      expect(runtimeLocale(locale)).toBe(locale);
    }
  });

  it("recovers the stored language from a runtime tag, English for unknown tags", () => {
    expect(messageLocale("ar-u-nu-arab")).toBe("ar");
    expect(messageLocale("de")).toBe("de");
    expect(messageLocale("xx-u-nu-arab")).toBe("en");
  });

  it("detects RTL from the stored language behind a runtime tag", () => {
    expect(htmlDirForLocale(messageLocale("ar-u-nu-arab"))).toBe("rtl");
    expect(htmlDirForLocale("ar")).toBe("rtl");
    expect(htmlDirForLocale("en")).toBe("ltr");
  });

  it("formats digits in Arabic-Indic under the runtime tag", () => {
    expect(new Intl.NumberFormat(runtimeLocale("ar")).format(1234)).toBe(
      "١٬٢٣٤"
    );
    expect(new Intl.NumberFormat(runtimeLocale("en")).format(1234)).toBe(
      "1,234"
    );
  });
});
