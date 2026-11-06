import { readFileSync } from "fs";
import { join } from "path";
import { render } from "@tests/setup/test-utils";
import type { IconFunctionComponent } from "@opal/types";
import * as illustrations from "@opal/illustrations";

type TokenFile = Record<string, { value: string }>;

const VIEWBOX_SIZE = 120;

type Mode = "light" | "dark";

// Token JSON is the only per-mode map keyed by CSS var name. Dist ships CSS and mobile maps.
function readTokens(mode: Mode): TokenFile {
  return JSON.parse(
    readFileSync(
      join(__dirname, "../../../shared/tokens", `semantic-${mode}.json`),
      "utf8"
    )
  )[mode];
}

const THEMES: Record<Mode, TokenFile> = {
  light: readTokens("light"),
  dark: readTokens("dark"),
};

const ILLUSTRATIONS: [string, IconFunctionComponent][] = Object.entries(
  illustrations
) as [string, IconFunctionComponent][];

function renderSvg(
  Illustration: IconFunctionComponent,
  size?: number
): SVGSVGElement {
  const { container } = render(<Illustration size={size} />);
  const svg: SVGSVGElement | null = container.querySelector("svg");
  if (svg === null) throw new Error("illustration rendered no svg");
  return svg;
}

// Stroke width in viewBox units on the stroked element or the nearest ancestor that sets it.
function strokeWidths(svg: SVGSVGElement): number[] {
  return Array.from(svg.querySelectorAll("[stroke]"))
    .filter((el) => el.getAttribute("stroke") !== "none")
    .map((el) =>
      Number(el.closest("[stroke-width]")?.getAttribute("stroke-width"))
    );
}

function paints(svg: SVGSVGElement): string[] {
  return [svg, ...Array.from(svg.querySelectorAll("*"))].flatMap((el) =>
    ["fill", "stroke"].flatMap((attr) => {
      const value: string | null = el.getAttribute(attr);
      return value === null || value === "none" ? [] : [value];
    })
  );
}

describe.each(ILLUSTRATIONS)("%s", (_name, Illustration) => {
  it("renders", () => {
    const svg: SVGSVGElement = renderSvg(Illustration, 64);
    expect(svg).toHaveAttribute("width", "64");
    expect(svg.querySelector("path")).not.toBeNull();
  });

  it.each<Mode>(["light", "dark"])(
    "paints only with theme tokens defined in %s",
    (mode) => {
      const values: string[] = paints(renderSvg(Illustration, 64));
      expect(values.length).toBeGreaterThan(0);
      const untokened: string[] = values.filter((value) => {
        const token: string | undefined = value.match(/^var\(--(.+)\)$/)?.[1];
        return token === undefined || !(token in THEMES[mode]);
      });
      expect(untokened).toEqual([]);
    }
  );

  // Without a size the line weight assumes the 120 px size.
  it.each<[number, number | undefined]>([
    [2.5, 64],
    [3.5, 120],
    [3.5, undefined],
  ])("draws %s px lines at size %s", (px, size) => {
    const widths: number[] = strokeWidths(renderSvg(Illustration, size));
    expect(widths.length).toBeGreaterThan(0);
    for (const width of widths) {
      expect((width * (size ?? VIEWBOX_SIZE)) / VIEWBOX_SIZE).toBeCloseTo(px);
    }
  });
});
