import { cpSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import pdfjsPackage from "pdfjs-dist/package.json" with { type: "json" };

const pdfjsRoot: string = dirname(
  fileURLToPath(import.meta.resolve("pdfjs-dist/package.json"))
);
const webRoot: string = fileURLToPath(new URL("../", import.meta.url));
const destination: string = join(webRoot, "public/pdfjs", pdfjsPackage.version);
const directories: string[] = [
  "cmaps",
  "standard_fonts",
  "wasm",
  "iccs",
  "web/images",
];

// Ship worker, fonts, and decoders from the same version as the client library.
mkdirSync(destination, { recursive: true });
for (const directory of directories) {
  cpSync(join(pdfjsRoot, directory), join(destination, directory), {
    recursive: true,
  });
}
cpSync(
  join(pdfjsRoot, "build/pdf.worker.min.mjs"),
  join(destination, "pdf.worker.min.mjs")
);
