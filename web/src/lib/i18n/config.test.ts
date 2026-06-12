import {
  DEFAULT_LOCALE,
  LOCALE_COOKIE,
  SUPPORTED_LOCALES,
  isSupportedLocale,
  resolveLocale,
} from "./config";

describe("i18n config", () => {
  it("defaults to Chinese", () => {
    expect(DEFAULT_LOCALE).toBe("zh");
  });

  it("uses the standard NEXT_LOCALE cookie name", () => {
    expect(LOCALE_COOKIE).toBe("NEXT_LOCALE");
  });

  it("supports zh and en", () => {
    expect(SUPPORTED_LOCALES).toEqual(["zh", "en"]);
  });

  it("recognizes supported locales", () => {
    expect(isSupportedLocale("zh")).toBe(true);
    expect(isSupportedLocale("en")).toBe(true);
    expect(isSupportedLocale("fr")).toBe(false);
    expect(isSupportedLocale(undefined)).toBe(false);
  });

  it("resolves unknown / missing values to the default", () => {
    expect(resolveLocale("en")).toBe("en");
    expect(resolveLocale("fr")).toBe("zh");
    expect(resolveLocale(undefined)).toBe("zh");
  });
});
