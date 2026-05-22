import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative, resolve, sep } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const srcDir = join(root, "src");
const distDir = join(root, "dist");

mkdirSync(distDir, { recursive: true });

function findCss(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...findCss(full));
    } else if (entry.isFile() && entry.name.endsWith(".css")) {
      out.push(full);
    }
  }
  return out;
}

const colorsCss = join(srcDir, "styles", "colors.css");
const referenceCss = join(srcDir, "_reference.css");
const rootCss = join(srcDir, "root.css");
const allCss = findCss(srcDir).sort();
// colors.css is a standalone artifact (dist/colors.css) — exclude from the main bundle.
// _reference.css and root.css have fixed positions in the bundle (first and second).
const leafCss = allCss.filter(
  (p) => p !== referenceCss && p !== rootCss && p !== colorsCss
);
// _reference.css carries `@import "tailwindcss"` + `@config` and must come
// first. root.css follows so design tokens are defined before any rule that
// consumes them. The remaining files are concatenated alphabetically.
const order = [referenceCss, rootCss, ...leafCss];

// Strip per-file `@reference` directives — they only exist for monorepo dev
// where each file is processed independently by PostCSS. In the concatenated
// bundle every rule is already in the same processing context as the leading
// `_reference.css`, so the directives are redundant and would also fail to
// resolve relative paths after bundling.
function stripReferenceDirectives(source) {
  return source.replace(/^@reference\s+['"][^'"]+['"];\s*\n?/gm, "");
}

// Strip @import directives whose target resolves to another file inside srcDir.
// Those files are already inlined into the bundle by findCss(), so the @import
// is redundant — exactly like @reference. Without this, relative paths like
// `../../core/interactive/shared.css` survive into dist/styles.css and fail to
// resolve when consumers import the package from npm (source files are not in
// the published "files" list).
function stripIntraPackageImports(source, filePath) {
  const fileDir = dirname(filePath);
  return source.replace(
    /@import\s+['"]([^'"]+)['"];\s*\n?/gm,
    (match, importPath) => {
      const resolved = resolve(fileDir, importPath);
      return resolved.startsWith(srcDir + sep) ? "" : match;
    }
  );
}

const parts = order.map((file) => {
  const rel = relative(srcDir, file);
  const raw = readFileSync(file, "utf8");
  const cleaned =
    file === referenceCss
      ? raw
      : stripIntraPackageImports(stripReferenceDirectives(raw), file);
  return `/* === ${rel} === */\n${cleaned.trimEnd()}\n`;
});

const bundled = parts.join("\n");
writeFileSync(join(distDir, "styles.css"), bundled);

console.log(
  `bundled ${order.length} css file(s) -> dist/styles.css (${bundled.length} bytes)`
);

// colors.css is a standalone design-token file — copy it verbatim to dist/.
// Consumers import it separately so they can override with their own theme.
const colorsRaw = readFileSync(colorsCss, "utf8");
writeFileSync(join(distDir, "colors.css"), colorsRaw);

console.log(`copied colors.css -> dist/colors.css (${colorsRaw.length} bytes)`);

// root.css = single-import entry point: _reference.css must be first so that
// @import "tailwindcss" precedes all :root {} declarations (CSS requires @import
// before any non-@charset/non-@layer rules). Colors are inserted after the
// reference header; the rest of the bundle follows.
const [refPart, ...remainingParts] = parts;
const colorPart = `/* === colors.css === */\n${colorsRaw.trimEnd()}\n`;
const rootBundled = [refPart, colorPart, ...remainingParts].join("\n");
writeFileSync(join(distDir, "root.css"), rootBundled);

console.log(`bundled root.css -> dist/root.css (${rootBundled.length} bytes)`);
