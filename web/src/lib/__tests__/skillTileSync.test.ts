/**
 * @jest-environment jsdom
 */
import { createElement } from "react";
import { render } from "@testing-library/react";
import SvgSparkle from "@opal/icons/sparkle";
import { TAG_COLORS } from "@opal/components/tag/colors";
import { createRichInputTileNode } from "@/lib/richInputTile";

// Guards the raw-DOM skill tile against drift from its source of truth (the Opal
// Tag + sparkle icon): the mirrored path must equal the real icon, and the
// fill/text colors must come from TAG_COLORS.blue.
describe("skill tile stays in sync with the Opal Tag + sparkle icon", () => {
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
    const { container } = render(createElement(SvgSparkle));
    const realPath = container.querySelector("path")?.getAttribute("d");
    const realCap = container
      .querySelector("[stroke-linecap]")
      ?.getAttribute("stroke-linecap");
    expect(realPath).toBeTruthy();
    expect(realCap).toBeTruthy();

    const tileIcon = skillTile().querySelector(".rich-input-tile-icon");
    expect(tileIcon?.querySelector("path")?.getAttribute("d")).toBe(realPath);
    expect(tileIcon?.getAttribute("stroke-linecap")).toBe(realCap);
  });

  it("sources fill + text colors from TAG_COLORS.blue", () => {
    const tile = skillTile();
    for (const cls of TAG_COLORS.blue.bg.split(" ")) {
      expect(tile.classList.contains(cls)).toBe(true);
    }
    const iconClass =
      tile.querySelector(".rich-input-tile-icon")?.getAttribute("class") ?? "";
    for (const cls of TAG_COLORS.blue.text.split(" ")) {
      expect(iconClass).toContain(cls);
    }
  });
});
