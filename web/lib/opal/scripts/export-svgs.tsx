// Renders opal logos and icons to standalone SVG files, e.g. for the docs site.
// Usage: bun lib/opal/scripts/export-svgs.tsx <map.json> <outRoot> [--check]
// Run from web/ after `bun lib/opal/scripts/bundle-css.mjs` (theme vars come from dist/root.css).
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { dirname, join, resolve } from "path";

interface Entry {
  out: string;
  src: string | string[];
  color?: string;
  size?: number;
  theme?: "light" | "dark";
  gapRatio?: number;
}

const OPAL_SRC = resolve(import.meta.dir, "../src");
const ROOT_CSS = resolve(import.meta.dir, "../dist/root.css");

function parseVars(css: string, selector: string): Map<string, string> {
  const vars = new Map<string, string>();
  const re = new RegExp(
    `(^|\\n)${selector.replace(".", "\\.")}\\s*\\{([^}]*)\\}`,
    "g"
  );
  for (const block of css.matchAll(re)) {
    for (const m of block[2]!.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      vars.set(m[1]!, m[2]!.trim());
    }
  }
  return vars;
}

function makeResolver(theme: "light" | "dark"): (v: string) => string {
  const css = readFileSync(ROOT_CSS, "utf8");
  const vars = parseVars(css, ":root");
  if (theme === "dark")
    parseVars(css, ".dark").forEach((v, k) => vars.set(k, v));
  const resolveVar = (value: string, depth = 0): string =>
    value.replace(/var\((--[\w-]+)\)/g, (_, name: string) => {
      const next = vars.get(name);
      if (next === undefined || depth > 10)
        throw new Error(`unknown CSS var ${name}`);
      return resolveVar(next, depth + 1);
    });
  return resolveVar;
}

// Turns Tailwind fill/stroke classes and CSS vars into plain SVG attributes.
function toStandalone(
  svg: string,
  entry: Entry,
  resolveVar: (v: string) => string
): string {
  const dark = entry.theme === "dark";
  let out = svg.replace(/ class="([^"]*)"/g, (_, cls: string) => {
    const attrs: string[] = [];
    for (const prop of ["fill", "stroke"]) {
      const light = cls.match(new RegExp(`(?:^|\\s)${prop}-\\[([^\\]]+)\\]`));
      const darkCls = cls.match(
        new RegExp(`dark:${prop}-(?:\\((--[\\w-]+)\\)|([\\w-]+))`)
      );
      if (dark && darkCls)
        attrs.push(`${prop}="var(${darkCls[1] ?? `--${darkCls[2]}`})"`);
      else if (light) attrs.push(`${prop}="${light[1]}"`);
    }
    return attrs.length ? " " + attrs.join(" ") : "";
  });
  out = out.replace(/var\(--[\w-]+\)/g, (v) => resolveVar(v));
  out = out.replace(/currentColor/g, entry.color ?? "#000000");
  if (!out.includes('xmlns="http://www.w3.org/2000/svg"')) {
    out = out.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
  }
  return out;
}

async function render(src: string, size: number): Promise<string> {
  const mod = (await import(join(OPAL_SRC, `${src}.tsx`))) as {
    default: ComponentType<{ size: number }>;
  };
  return renderToStaticMarkup(createElement(mod.default, { size }));
}

// Places several SVGs side by side in one SVG of the given height.
function compose(parts: string[], height: number, gap: number): string {
  let x = 0;
  const inner = parts.map((svg) => {
    const [, , w, h] = svg
      .match(/viewBox="([^"]+)"/)![1]!
      .split(/[\s,]+/)
      .map(Number) as number[];
    const width = (height * w!) / h!;
    const placed = svg
      .replace(/^<svg([^>]*?) (?:width|height)="[^"]*"/, "<svg$1")
      .replace(/^<svg([^>]*?) (?:width|height)="[^"]*"/, "<svg$1")
      .replace("<svg", `<svg x="${x}" width="${width}" height="${height}"`);
    x += width + gap;
    return placed;
  });
  const total = x - gap;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${total}" height="${height}" viewBox="0 0 ${total} ${height}" fill="none">${inner.join("")}</svg>`;
}

async function main(): Promise<void> {
  const [mapPath, outRoot] = process.argv.slice(2);
  const check = process.argv.includes("--check");
  if (!mapPath || !outRoot)
    throw new Error("usage: export-svgs.tsx <map.json> <outRoot> [--check]");
  const { assets } = JSON.parse(readFileSync(mapPath, "utf8")) as {
    assets: Entry[];
  };
  const resolvers = {
    light: makeResolver("light"),
    dark: makeResolver("dark"),
  };
  const stale: string[] = [];
  for (const entry of assets) {
    const size = entry.size ?? 48;
    const srcs = Array.isArray(entry.src) ? entry.src : [entry.src];
    const parts = await Promise.all(srcs.map((s) => render(s, size)));
    const svg =
      parts.length === 1
        ? parts[0]!
        : compose(parts, size, size * (entry.gapRatio ?? 0));
    const result =
      toStandalone(svg, entry, resolvers[entry.theme ?? "light"]) + "\n";
    const target = join(outRoot, entry.out);
    if (check) {
      if (!existsSync(target) || readFileSync(target, "utf8") !== result)
        stale.push(entry.out);
      continue;
    }
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, result);
  }
  if (stale.length)
    throw new Error(`stale or missing generated SVGs:\n${stale.join("\n")}`);
  console.log(
    `${check ? "checked" : "wrote"} ${assets.length} SVGs under ${outRoot}`
  );
}

await main();
