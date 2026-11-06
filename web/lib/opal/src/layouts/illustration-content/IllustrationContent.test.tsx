import { render, screen } from "@tests/setup/test-utils";
import { IllustrationContent } from "@opal/layouts";
import { SvgLongWait } from "@opal/illustrations";
import { illustrationStrokeWidth } from "@opal/illustrations/line-weight";

describe("IllustrationContent", () => {
  it("sizes the illustration at 120 so it draws the 120 px line weight", () => {
    const { container } = render(
      <IllustrationContent illustration={SvgLongWait} title="No results" />
    );
    const svg: SVGSVGElement | null = container.querySelector("svg");

    expect(svg).toHaveClass("w-30", "h-30");
    expect(svg).toHaveAttribute("width", "120");
    expect(svg).toHaveAttribute("stroke-width", "3.5");
    expect(screen.getByText("No results")).toHaveClass(
      "font-main-content-emphasis",
      "text-text-04"
    );
  });

  it("sm draws the illustration at 64 with its 64px line weight and a muted title", () => {
    const { container } = render(
      <IllustrationContent
        size="sm"
        illustration={SvgLongWait}
        title="No recent activity"
      />
    );
    const svg: SVGSVGElement | null = container.querySelector("svg");

    expect(svg).toHaveAttribute("width", "64");
    expect(svg).toHaveAttribute("height", "64");
    expect(svg).not.toHaveClass("w-30");
    expect(svg).toHaveAttribute(
      "stroke-width",
      String(illustrationStrokeWidth(64))
    );
    expect(screen.getByText("No recent activity")).toHaveClass(
      "font-main-ui-muted",
      "text-text-03"
    );
  });
});
