import { render } from "@tests/setup/test-utils";
import SvgLongWait from "@opal/illustrations/long-wait";
import { IllustrationContent } from "@opal/layouts";

describe("IllustrationContent", () => {
  it("sizes the illustration at 120 so it draws the 120 px line weight", () => {
    const { container } = render(
      <IllustrationContent illustration={SvgLongWait} title="No items" />
    );
    const svg: SVGSVGElement | null = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "120");
    expect(svg).toHaveAttribute("stroke-width", "3.5");
  });
});
