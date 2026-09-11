import { ensureHrefProtocol, expectDefined, transformLinkUri } from "./utils";

describe("expectDefined", () => {
  it("returns defined values unchanged", () => {
    const obj = { a: 1 };
    expect(expectDefined(obj, "missing")).toBe(obj);
    expect(expectDefined("value", "missing")).toBe("value");
  });

  it("returns falsy values that are not null or undefined", () => {
    expect(expectDefined(0, "missing")).toBe(0);
    expect(expectDefined("", "missing")).toBe("");
    expect(expectDefined(false, "missing")).toBe(false);
    expect(Number.isNaN(expectDefined(NaN, "missing"))).toBe(true);
  });

  it("throws with the message for null", () => {
    expect(() => expectDefined(null, "value is null")).toThrow(
      new Error("value is null")
    );
  });

  it("throws with the message for undefined", () => {
    expect(() => expectDefined(undefined, "value is undefined")).toThrow(
      new Error("value is undefined")
    );
  });
});

describe("ensureHrefProtocol", () => {
  it("adds https protocol to bare domains", () => {
    expect(ensureHrefProtocol("anthropic.com")).toBe("https://anthropic.com");
  });

  it("preserves links that already include a protocol", () => {
    expect(ensureHrefProtocol("https://anthropic.com")).toBe(
      "https://anthropic.com"
    );
    expect(ensureHrefProtocol("mailto:support@anthropic.com")).toBe(
      "mailto:support@anthropic.com"
    );
  });

  it("converts bare email addresses to mailto links", () => {
    expect(ensureHrefProtocol("support@anthropic.com")).toBe(
      "mailto:support@anthropic.com"
    );
  });
});

describe("transformLinkUri", () => {
  it("allows safe protocols", () => {
    expect(transformLinkUri("https://anthropic.com")).toBe(
      "https://anthropic.com"
    );
    expect(transformLinkUri("mailto:support@anthropic.com")).toBe(
      "mailto:support@anthropic.com"
    );
  });

  it("converts bare email addresses to mailto links", () => {
    expect(transformLinkUri("support@anthropic.com")).toBe(
      "mailto:support@anthropic.com"
    );
  });

  it("blocks unsafe protocols", () => {
    expect(transformLinkUri("javascript:alert(1)")).toBeNull();
  });
});
