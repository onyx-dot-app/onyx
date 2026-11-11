import { readFileSync } from "fs";
import { join } from "path";

type TokenFile = Record<string, { value: string }>;

// Reads the token sources because lib/shared/dist is not built before Jest runs.
function readTokens(file: string): Record<string, TokenFile> {
  return JSON.parse(
    readFileSync(join(__dirname, "../shared/tokens", file), "utf8")
  );
}

const PRIMITIVES: TokenFile = readTokens("primitives.json") as TokenFile;
const THEMES: Record<"light" | "dark", TokenFile> = {
  light: readTokens("semantic-light.json").light,
  dark: readTokens("semantic-dark.json").dark,
};
const PRESET: string = readFileSync(
  join(__dirname, "tailwind-preset.cjs"),
  "utf8"
);
const CHART_TOKENS: string[] = Object.keys(THEMES.light).filter((name) =>
  name.startsWith("chart-")
);

describe("chart color tokens", () => {
  it("defines the 17 Figma chart colors", () => {
    expect(CHART_TOKENS).toHaveLength(17);
  });

  it.each(["light", "dark"] as const)(
    "references a primitive for every chart color in %s",
    (mode) => {
      const unresolved: string[] = CHART_TOKENS.filter((name) => {
        const ref: string | undefined =
          THEMES[mode][name]?.value.match(/^\{(.+)\}$/)?.[1];
        return ref === undefined || !(ref in PRIMITIVES);
      });
      expect(unresolved).toEqual([]);
    }
  );

  it("maps every chart color to a Tailwind class", () => {
    for (const name of CHART_TOKENS) {
      expect(PRESET).toContain(`"${name}": "var(--${name})"`);
    }
  });
});
