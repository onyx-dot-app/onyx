/** @jest-environment jsdom */

import {
  applyAppearance,
  DEFAULT_APPEARANCE_PREFERENCES,
  parseAppearanceCookie,
} from "@/lib/appearance/preferences";

describe("parseAppearanceCookie", () => {
  it("reads the fields the backend writes", () => {
    expect(
      parseAppearanceCookie("interface_font=opendyslexic&response_font=default")
    ).toEqual({ interface_font: "opendyslexic", response_font: "default" });
  });

  it("ignores unknown fields", () => {
    expect(
      parseAppearanceCookie("motion=reduced&interface_font=system")
    ).toEqual({ interface_font: "system", response_font: "match" });
  });

  it.each([
    undefined,
    "",
    "garbage",
    "interface_font=comic-sans&response_font=",
    "=default&interface_font",
    "interface_font:opendyslexic|response_font:default",
  ])("falls back to the defaults for %p", (cookie) => {
    expect(parseAppearanceCookie(cookie)).toEqual(
      DEFAULT_APPEARANCE_PREFERENCES
    );
  });
});

describe("applyAppearance", () => {
  it("sets both font attributes and replaces earlier values", () => {
    const root = document.createElement("html");

    applyAppearance(
      { interface_font: "opendyslexic", response_font: "default" },
      root
    );
    expect(root.getAttribute("data-interface-font")).toBe("opendyslexic");
    expect(root.getAttribute("data-response-font")).toBe("default");

    applyAppearance(DEFAULT_APPEARANCE_PREFERENCES, root);
    expect(root.getAttribute("data-interface-font")).toBe("default");
    expect(root.getAttribute("data-response-font")).toBe("match");
  });

  it("targets the document root by default", () => {
    applyAppearance({ interface_font: "system", response_font: "match" });

    expect(document.documentElement.dataset.interfaceFont).toBe("system");
    expect(document.documentElement.dataset.responseFont).toBe("match");
  });
});
