import { describe, expect, it } from "@jest/globals";
import { makeItem } from "@/chat/__tests__/fixtures";
import { getToolIcon } from "@/components/chat/timeline/toolIcons";
import SvgGlobe from "@/icons/globe";
import SvgSearch from "@/icons/search";
import SvgCpu from "@/icons/cpu";
describe("tool icons", () => {
  it("distinguishes search tools and custom tools", () => {
    for (const [name, icon] of [
      ["web_search", SvgGlobe],
      ["internal_search", SvgSearch],
      ["custom", SvgCpu],
    ] as const)
      expect(
        getToolIcon([
          makeItem({
            kind: "tool",
            name,
            arguments: {},
            status: "running",
            output: "",
            metadata: null,
          }),
        ]),
      ).toBe(icon);
  });
});
