import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative, resolve, sep } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
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

const referenceCss = join(srcDir, "_reference.css");
const rootCss = join(srcDir, "root.css");
const allCss = findCss(srcDir).sort();
// _reference.css and root.css have fixed positions in the bundle (first and second).
const leafCss = allCss.filter((p) => p !== referenceCss && p !== rootCss);
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
      // Only relative imports (starting with . or ..) can be intra-package.
      // Bare specifiers like "tailwindcss" are external packages and must be kept.
      if (!importPath.startsWith(".")) return match;
      const resolved = resolve(fileDir, importPath);
      return resolved.startsWith(srcDir + sep) ? "" : match;
    }
  );
}

// Inline `@import "@onyx-ai/shared/*.css"` by splicing in the resolved file's
// contents, so the published opal artifact is SELF-CONTAINED and has no runtime
// dependency on @onyx-ai/shared. Opal still consumes shared as the build-time
// source of truth (shared must be built first), but consumers of the published
// package get the design tokens baked into dist/root.css. Other bare imports
// (tailwindcss, tw-animate-css) are left untouched for the consumer's Tailwind.
function inlineSharedImports(source) {
  return source.replace(
    /@import\s+['"](@onyx-ai\/shared\/[^'"]+)['"];[ \t]*\n?/gm,
    (_match, spec) => {
      const resolved = require.resolve(spec);
      const css = readFileSync(resolved, "utf8").trimEnd();
      return `/* inlined ${spec} */\n${css}\n`;
    }
  );
}

const parts = order.map((file) => {
  const rel = relative(srcDir, file);
  const raw = readFileSync(file, "utf8");
  const cleaned = inlineSharedImports(
    stripIntraPackageImports(
      file === referenceCss ? raw : stripReferenceDirectives(raw),
      file
    )
  );
  return `/* === ${rel} === */\n${cleaned.trimEnd()}\n`;
});

const bundled = parts.join("\n");
writeFileSync(join(distDir, "styles.css"), bundled);
writeFileSync(join(distDir, "root.css"), bundled);

console.log(
  `bundled ${order.length} css file(s) -> dist/styles.css + dist/root.css (${bundled.length} bytes)`
);
