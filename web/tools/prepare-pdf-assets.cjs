// Serve PDF.js support files from the same origin, pinned to the renderer version.
const { cpSync, mkdirSync } = require("node:fs");
const path = require("node:path");
const pdfjsRoot = path.dirname(require.resolve("pdfjs-dist/package.json"));
const pdfjsVersion = require("pdfjs-dist/package.json").version;
const pdfjsAssets = path.join(__dirname, "..", "public", "pdfjs", pdfjsVersion);
mkdirSync(pdfjsAssets, { recursive: true });
for (const directory of ["cmaps", "standard_fonts", "wasm", "iccs"]) {
  cpSync(path.join(pdfjsRoot, directory), path.join(pdfjsAssets, directory), {
    recursive: true,
  });
}
cpSync(
  path.join(pdfjsRoot, "build/pdf.worker.min.mjs"),
  path.join(pdfjsAssets, "pdf.worker.min.mjs")
);
