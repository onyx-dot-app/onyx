import { readFileSync } from "fs";
import { join } from "path";
import { render } from "@tests/setup/test-utils";
import type { IconFunctionComponent } from "@opal/types";
import * as illustrations from "@opal/illustrations";

type TokenFile = Record<string, { value: string }>;

const VIEWBOX_SIZE = 120;

// Reads the token sources because lib/shared/dist is not built before Jest runs.
function readTokens(file: string, mode: "light" | "dark"): TokenFile {
  return JSON.parse(
    readFileSync(join(__dirname, "../../../shared/tokens", file), "utf8")
  )[mode];
}

const THEMES: Record<"light" | "dark", TokenFile> = {
  light: readTokens("semantic-light.json", "light"),
  dark: readTokens("semantic-dark.json", "dark"),
};

const ILLUSTRATIONS: [string, IconFunctionComponent][] = Object.entries(
  illustrations
) as [string, IconFunctionComponent][];

const SOURCES: [string, string][] = readFileSync(
  join(__dirname, "index.ts"),
  "utf8"
)
  .split("\n")
  .flatMap((line) => {
    const file: string | undefined = line.match(
      /from "@opal\/illustrations\/(.+)"/
    )?.[1];
    return file === undefined
      ? []
      : [[file, readFileSync(join(__dirname, `${file}.tsx`), "utf8")]];
  });

function renderSvg(Illustration: IconFunctionComponent, size?: number) {
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

describe("illustration sources", () => {
  it("lists every exported illustration", () => {
    expect(SOURCES).toHaveLength(ILLUSTRATIONS.length);
  });

  it.each(SOURCES)("%s has no hex color literal", (_file, source) => {
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });
});

describe.each(ILLUSTRATIONS)("%s", (_name, Illustration) => {
  it("renders", () => {
    const svg: SVGSVGElement = renderSvg(Illustration, 64);
    expect(svg).toHaveAttribute("width", "64");
    expect(svg.querySelector("path")).not.toBeNull();
  });

  it.each(["light", "dark"] as const)(
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

  it("draws 2.5 px lines at 64", () => {
    const widths: number[] = strokeWidths(renderSvg(Illustration, 64));
    expect(widths.length).toBeGreaterThan(0);
    for (const width of widths) {
      expect((width * 64) / VIEWBOX_SIZE).toBeCloseTo(2.5);
    }
  });

  it.each([120, undefined])("keeps 3.5 px lines at size %s", (size) => {
    const widths: number[] = strokeWidths(renderSvg(Illustration, size));
    expect(widths.length).toBeGreaterThan(0);
    for (const width of widths) {
      expect(width).toBeCloseTo(3.5);
    }
  });
});
