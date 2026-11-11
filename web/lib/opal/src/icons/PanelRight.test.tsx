import { render } from "@tests/setup/test-utils";
import { SvgPanelRight } from "@opal/icons";

describe("SvgPanelRight", () => {
  it("draws the divider on the right, unlike SvgSidebar", () => {
    const { container } = render(<SvgPanelRight size={16} />);

    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "16");
    expect(svg).toHaveAttribute("stroke", "currentColor");
    expect(svg?.querySelector("path")?.getAttribute("d")).toMatch(
      /^M10 2V14M10 2H3\.33333/
    );
  });
});
