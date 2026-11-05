/**
 * @jest-environment jsdom
 */
import { createElement } from "react";
import type { ComponentType } from "react";
import { render } from "@testing-library/react";
import SvgSparkle from "@opal/icons/sparkle";
import SvgClipboard from "@opal/icons/clipboard";
import { BADGE_COLORS, badgeTextClass } from "@opal/components/badge/colors";
import type { StatusColor } from "@opal/types";
import { createRichInputTileNode } from "@/lib/richInputTile";

// Guards the raw-DOM tiles against drift from their source of truth (the Opal
// Badge + icons): the mirrored path must equal the real icon, and the fill/text
// colors must come from the badge colours (blue for skill, gray for paste).

function expectIconMirrors(tile: HTMLElement, realIcon: ComponentType) {
  const { container } = render(createElement(realIcon));
  const realPath = container.querySelector("path")?.getAttribute("d");
  const realCap = container
    .querySelector("[stroke-linecap]")
    ?.getAttribute("stroke-linecap");
  expect(realPath).toBeTruthy();
  expect(realCap).toBeTruthy();

  const tileIcon = tile.querySelector(".rich-input-tile-icon");
  expect(tileIcon?.querySelector("path")?.getAttribute("d")).toBe(realPath);
  expect(tileIcon?.getAttribute("stroke-linecap")).toBe(realCap);
}

function expectColorsFromTag(tile: HTMLElement, color: StatusColor) {
  for (const cls of BADGE_COLORS[color].bg.split(" ")) {
    expect(tile.classList.contains(cls)).toBe(true);
  }
  for (const selector of [
    ".rich-input-tile-icon",
    ".rich-input-tile-preview",
  ]) {
    const elClass = tile.querySelector(selector)?.getAttribute("class") ?? "";
    for (const cls of badgeTextClass(color).split(" ")) {
      expect(elClass).toContain(cls);
    }
  }
}

describe("skill tile stays in sync with the Opal Badge + sparkle icon", () => {
  function skillTile() {
    return createRichInputTileNode({
      type: "skill",
      text: "/pptx ",
      preview: "Skill: Slides",
      meta: "",
      skillSlug: "pptx",
    });
  }

  it("mirrors the real SvgSparkle path + stroke-linecap", () => {
    expectIconMirrors(skillTile(), SvgSparkle);
  });

  it("sources fill + text colors from BADGE_COLORS.blue", () => {
    expectColorsFromTag(skillTile(), "info");
  });
});

describe("paste tile stays in sync with the Opal Badge + clipboard icon", () => {
  function pasteTile() {
    return createRichInputTileNode({
      type: "paste",
      text: "some long pasted text",
      preview: "some long pasted…",
      meta: "21 chars",
    });
  }

  it("mirrors the real SvgClipboard path + stroke-linecap", () => {
    expectIconMirrors(pasteTile(), SvgClipboard);
  });

  it("sources fill + text colors from BADGE_COLORS.gray", () => {
    expectColorsFromTag(pasteTile(), "default");
  });
});
