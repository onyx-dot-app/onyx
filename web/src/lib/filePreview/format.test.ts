import { resolveFilePreviewFormat } from "@/lib/filePreview/format";

test.each([
  ["script.py", "text/x-python", { kind: "code", language: "python" }],
  // HTML and SVG show their source, never a rendered page or image
  ["page.html", "text/html", { kind: "code", language: "html" }],
  ["logo.svg", "image/svg+xml", { kind: "code", language: "xml" }],
  ["logo.svg", "application/octet-stream", { kind: "code", language: "xml" }],
  ["chart.png", "image/png", { kind: "image" }],
  ["report.pdf", "application/octet-stream", { kind: "pdf" }],
  ["data.csv", "text/plain", { kind: "csv" }],
  ["book.xlsx", "application/octet-stream", { kind: "spreadsheet" }],
  ["macros.xlsm", "application/octet-stream", { kind: "spreadsheet" }],
  [
    "renamed",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    { kind: "spreadsheet" },
  ],
  ["notes.md", "text/plain", { kind: "markdown" }],
  ["notes", "text/markdown; charset=utf-8", { kind: "markdown" }],
  ["letter.docx", "application/octet-stream", { kind: "docx" }],
  // Legacy Word files have no previewer
  ["letter.doc", "application/msword", { kind: "unsupported" }],
  [
    "server.log",
    "application/octet-stream",
    { kind: "code", language: "plaintext" },
  ],
  ["config.json", "application/json", { kind: "code", language: "json" }],
  // A data extension wins over a plain text type
  ["config.json", "text/plain", { kind: "code", language: "json" }],
  ["feed.xml", "text/plain", { kind: "code", language: "xml" }],
  // An extension wins over any MIME type, not only a plain text one
  ["config.json", "text/markdown", { kind: "code", language: "json" }],
  ["data.csv", "application/pdf", { kind: "csv" }],
  ["report.pdf", "image/png", { kind: "pdf" }],
  ["notes.txt", "text/plain", { kind: "code", language: "plaintext" }],
  ["deck.pptx", "application/octet-stream", { kind: "pptx" }],
  [
    "renamed",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    { kind: "pptx" },
  ],
  // Legacy PowerPoint files have no previewer
  ["deck.ppt", "application/vnd.ms-powerpoint", { kind: "unsupported" }],
  ["archive.zip", "application/zip", { kind: "unsupported" }],
])("%s (%s) previews as %j", (name, mimeType, expected) => {
  expect(resolveFilePreviewFormat(name, mimeType)).toEqual(expected);
});
