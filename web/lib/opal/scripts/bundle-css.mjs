import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

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

const colorsCss = join(srcDir, "colors.css");
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

const parts = order.map((file) => {
  const rel = relative(srcDir, file);
  const raw = readFileSync(file, "utf8");
  const cleaned = file === referenceCss ? raw : stripReferenceDirectives(raw);
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

// root.css = colors + styles in a single file so consumers need only one import.
const rootBundled = colorsRaw.trimEnd() + "\n\n" + bundled;
writeFileSync(join(distDir, "root.css"), rootBundled);

console.log(`bundled root.css -> dist/root.css (${rootBundled.length} bytes)`);
