import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative, sep } from "node:path";
import postcss from "postcss";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const srcDir = join(root, "src");
const distDir = join(root, "dist");

mkdirSync(distDir, { recursive: true });

const colorsCss = join(srcDir, "styles", "colors.css");
const referenceCss = join(srcDir, "_reference.css");
const rootCss = join(srcDir, "root.css");

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

// Clean a CSS file for inclusion in the bundle, using the PostCSS AST so that
// trailing comments, multi-line directives, url() syntax and CRLF line endings
// can't defeat the transformation (regex stripping is the classic flaky trap).
//
//  - `@reference` is always removed: it only exists for monorepo dev where each
//    file is processed independently. In the concatenated bundle every rule is
//    already behind the leading `@import "tailwindcss"`, so it's redundant.
//  - Relative `@import`s that resolve inside srcDir are removed: those files are
//    already inlined into the bundle by findCss(). Leaving them would break npm
//    consumers, since source files aren't in the published package.
//  - Bare specifiers (e.g. `@import "tailwindcss"`) are kept — they have no
//    ./ ../ or / prefix and must survive into the bundle.
function clean(source, filePath) {
  const ast = postcss.parse(source, { from: filePath });
  ast.walkAtRules((rule) => {
    if (rule.name === "reference") {
      rule.remove();
      return;
    }
    if (rule.name === "import") {
      const m = rule.params.match(/^\s*(?:url\()?\s*['"]([^'"]+)['"]/);
      if (m) {
        const spec = m[1];
        const isRelative =
          spec.startsWith("./") ||
          spec.startsWith("../") ||
          spec.startsWith("/");
        if (isRelative) {
          const resolved = join(dirname(filePath), spec);
          if (resolved.startsWith(srcDir + sep)) rule.remove();
        }
      }
    }
  });
  return ast.toString();
}

// dbg.css contains dev-only debugging utilities and is excluded from the bundle.
// It is imported by _reference.css for @apply resolution during authoring only.
const dbgCss = join(srcDir, "styles", "dbg.css");

// colors.css is a standalone artifact (dist/colors.css) — exclude from the main
// bundle. _reference.css and root.css have fixed positions (first and second).
// The remaining files are concatenated alphabetically; they are independent
// (no shared selectors), so order between them is not load-bearing.
const allCss = findCss(srcDir).sort();
const leafCss = allCss.filter(
  (p) => p !== referenceCss && p !== rootCss && p !== dbgCss
);
const order = [referenceCss, rootCss, ...leafCss];

const parts = order.map((file) => {
  const rel = relative(srcDir, file);
  const raw = readFileSync(file, "utf8");
  const cleaned = clean(raw, file);
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
// @import "tailwindcss" precedes all :root {} declarations (CSS requires
// @import before any non-@charset/non-@layer rule). colors.css is inlined
// after the reference header; the rest of the bundle follows.
const [refPart, ...remainingParts] = parts;
const colorPart = `/* === colors.css === */\n${colorsRaw.trimEnd()}\n`;
const rootBundled = [refPart, colorPart, ...remainingParts].join("\n");
writeFileSync(join(distDir, "root.css"), rootBundled);
console.log(`bundled root.css -> dist/root.css (${rootBundled.length} bytes)`);
