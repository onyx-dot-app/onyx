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

const rootCss = join(srcDir, "root.css");
const allCss = findCss(srcDir).sort();
const leafCss = allCss.filter((p) => p !== rootCss);
const order = [rootCss, ...leafCss];

const parts = order.map((file) => {
  const rel = relative(srcDir, file);
  return `/* === ${rel} === */\n${readFileSync(file, "utf8").trimEnd()}\n`;
});

const bundled = parts.join("\n");
writeFileSync(join(distDir, "styles.css"), bundled);

console.log(
  `bundled ${order.length} css file(s) -> dist/styles.css (${bundled.length} bytes)`
);
