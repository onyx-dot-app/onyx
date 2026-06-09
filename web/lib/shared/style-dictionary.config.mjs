// Style Dictionary build script (programmatic API, Style Dictionary v4).
//
// Single token source (tokens/**/*.json) -> two platform outputs:
//   - web:    dist/tokens.css  (CSS custom properties, units applied, e.g. 16px)
//   - mobile: dist/tokens.js + dist/tokens.d.ts (typed JS object, unitless numbers)
//
// Run via `node style-dictionary.config.mjs` (wired as the `build:tokens` script).
// This file is build-time only — `style-dictionary` is a devDependency and never
// ships in the package output, so it cannot affect consumers' runtime dependency graphs.

import StyleDictionary from "style-dictionary";

const isDimension = (token) => (token.type ?? token.$type) === "dimension";
const rawValue = (token) => token.value ?? token.$value;

// Web wants CSS dimensions with units (e.g. "16px").
StyleDictionary.registerTransform({
  name: "size/sh-px",
  type: "value",
  filter: isDimension,
  transform: (token) => `${rawValue(token)}px`,
});

// React Native wants unitless numbers (e.g. 16) for style objects.
StyleDictionary.registerTransform({
  name: "size/sh-unitless",
  type: "value",
  filter: isDimension,
  transform: (token) => Number(rawValue(token)),
});

const sd = new StyleDictionary({
  source: ["tokens/**/*.json"],
  // Token sources are authored in the legacy { value, type } shape.
  log: { verbosity: "default" },
  platforms: {
    // ---- Web: CSS custom properties (namespaced `--sh-*` to avoid colliding
    // with Opal's existing `--color-*` / `--text-*` variables) ----
    css: {
      transforms: ["attribute/cti", "name/kebab", "color/css", "size/sh-px"],
      prefix: "sh",
      buildPath: "dist/",
      files: [
        {
          destination: "tokens.css",
          format: "css/variables",
        },
      ],
    },
    // ---- Mobile: typed JS object + declarations ----
    ts: {
      transforms: [
        "attribute/cti",
        "name/camel",
        "color/hex",
        "size/sh-unitless",
      ],
      buildPath: "dist/",
      files: [
        {
          destination: "tokens.js",
          format: "javascript/es6",
        },
        {
          destination: "tokens.d.ts",
          format: "typescript/es6-declarations",
        },
      ],
    },
  },
});

await sd.buildAllPlatforms();
