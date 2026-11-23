/** @jest-environment jsdom */

import {
  applyAppearance,
  DEFAULT_APPEARANCE_PREFERENCES,
  parseAppearanceCookie,
} from "@/lib/appearance/preferences";
import { prefersReducedMotion } from "@opal/utils";

describe("parseAppearanceCookie", () => {
  it("reads the fields the backend writes", () => {
    expect(
      parseAppearanceCookie(
        "interface_font=opendyslexic&response_font=default&motion=reduced"
      )
    ).toEqual({
      interface_font: "opendyslexic",
      response_font: "default",
      motion: "reduced",
    });
  });

  it("ignores unknown fields", () => {
    expect(
      parseAppearanceCookie("contrast=high&interface_font=system")
    ).toEqual({
      interface_font: "system",
      response_font: "match",
      motion: "system",
    });
  });

  it.each([
    undefined,
    "",
    "garbage",
    "interface_font=comic-sans&response_font=&motion=none",
    "=default&interface_font",
    "interface_font:opendyslexic|response_font:default|motion:reduced",
  ])("falls back to the defaults for %p", (cookie) => {
    expect(parseAppearanceCookie(cookie)).toEqual(
      DEFAULT_APPEARANCE_PREFERENCES
    );
  });
});

describe("applyAppearance", () => {
  it("sets every attribute and replaces earlier values", () => {
    const root = document.createElement("html");

    applyAppearance(
      {
        interface_font: "opendyslexic",
        response_font: "default",
        motion: "reduced",
      },
      root
    );
    expect(root.getAttribute("data-interface-font")).toBe("opendyslexic");
    expect(root.getAttribute("data-response-font")).toBe("default");
    expect(root.getAttribute("data-motion")).toBe("reduced");

    applyAppearance(DEFAULT_APPEARANCE_PREFERENCES, root);
    expect(root.getAttribute("data-interface-font")).toBe("default");
    expect(root.getAttribute("data-response-font")).toBe("match");
    expect(root.getAttribute("data-motion")).toBe("system");
  });

  it("targets the document root by default", () => {
    applyAppearance({
      interface_font: "system",
      response_font: "match",
      motion: "system",
    });

    expect(document.documentElement.dataset.interfaceFont).toBe("system");
    expect(document.documentElement.dataset.responseFont).toBe("match");
  });
});

describe("motion", () => {
  const originalMatchMedia = window.matchMedia;

  function mockOsReducedMotion(reduce: boolean) {
    window.matchMedia = jest.fn().mockImplementation((query: string) => ({
      matches: reduce && query === "(prefers-reduced-motion: reduce)",
      media: query,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    }));
  }

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
    applyAppearance(DEFAULT_APPEARANCE_PREFERENCES);
  });

  it("reduced reduces motion even when the OS does not ask for it", () => {
    mockOsReducedMotion(false);
    applyAppearance({ ...DEFAULT_APPEARANCE_PREFERENCES, motion: "reduced" });
    expect(prefersReducedMotion()).toBe(true);

    applyAppearance(DEFAULT_APPEARANCE_PREFERENCES);
    expect(prefersReducedMotion()).toBe(false);
  });

  it("system follows the OS", () => {
    mockOsReducedMotion(true);
    applyAppearance(DEFAULT_APPEARANCE_PREFERENCES);
    expect(prefersReducedMotion()).toBe(true);
  });
});
