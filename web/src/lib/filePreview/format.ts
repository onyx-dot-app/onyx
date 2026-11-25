import {
  getCodeLanguage,
  getDataLanguage,
  getLanguageByMime,
  isMarkdownFile,
} from "@/lib/languages";

/**
 * How a file previews. Code, text and data files share `code`; HTML and SVG
 * also render, with their source a toggle away. A Word or PowerPoint file
 * (`office`) previews as a PDF that the server converts.
 */
export type FilePreviewFormat =
  | { kind: "code"; language: string; render?: "html" | "svg" }
  | { kind: "markdown" }
  | { kind: "csv" }
  | { kind: "spreadsheet" }
  | { kind: "pdf" }
  | { kind: "office" }
  | { kind: "image" }
  | { kind: "unsupported" };

const SPREADSHEET_MIME_TYPES = [
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel.sheet.macroenabled.12",
];
// Matches the types the server converts to a PDF: RENDER_PREVIEW_PDF_MIME_TYPES
// in backend/onyx/server/features/build/sandbox/harness_base.py
const OFFICE_MIME_TYPES = [
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
];
const MARKDOWN_MIME_TYPES = [
  "text/markdown",
  "text/x-markdown",
  "text/x-rst",
  "text/x-org",
];
const TEXT_MIME_TYPES = [
  "text/plain",
  "text/x-log",
  "text/x-config",
  "text/tab-separated-values",
];
const TEXT_EXTENSIONS = /\.(txt|log|conf|tsv)$/i;

/** An SVG's text as an image URL. */
export function svgDataUrl(text: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(text)}`;
}

/**
 * Picks a file's preview from its name, then from its MIME type: a known
 * extension always wins over the MIME type, so `config.json` shows as JSON
 * whatever type it is served with. SVG loads as text: the server sends it
 * without an image type, so it cannot load in an `<img>` from its URL. Other
 * images show by MIME type only.
 */
export function resolveFilePreviewFormat(
  fileName: string,
  mimeType: string
): FilePreviewFormat {
  const name = fileName.toLowerCase();
  const mime = mimeType.split(";")[0]?.trim().toLowerCase() ?? "";

  const codeLanguage = getCodeLanguage(name);
  if (codeLanguage === "html")
    return { kind: "code", language: "html", render: "html" };
  if (codeLanguage) return { kind: "code", language: codeLanguage };
  if (name.endsWith(".svg"))
    return { kind: "code", language: "xml", render: "svg" };
  if (name.endsWith(".pdf")) return { kind: "pdf" };
  if (name.endsWith(".csv")) return { kind: "csv" };
  if (/\.xls[xm]$/.test(name)) return { kind: "spreadsheet" };
  if (isMarkdownFile(name)) return { kind: "markdown" };
  if (/\.(docx|pptx)$/.test(name)) return { kind: "office" };
  if (TEXT_EXTENSIONS.test(name))
    return { kind: "code", language: "plaintext" };
  const dataLanguage = getDataLanguage(name);
  if (dataLanguage) return { kind: "code", language: dataLanguage };

  if (mime === "image/svg+xml")
    return { kind: "code", language: "xml", render: "svg" };
  if (mime.startsWith("image/")) return { kind: "image" };
  if (mime === "application/pdf") return { kind: "pdf" };
  if (mime === "text/csv") return { kind: "csv" };
  if (SPREADSHEET_MIME_TYPES.includes(mime)) return { kind: "spreadsheet" };
  if (MARKDOWN_MIME_TYPES.includes(mime)) return { kind: "markdown" };
  if (OFFICE_MIME_TYPES.includes(mime)) return { kind: "office" };
  if (TEXT_MIME_TYPES.includes(mime))
    return { kind: "code", language: "plaintext" };
  const mimeLanguage = getLanguageByMime(mime);
  if (mimeLanguage) return { kind: "code", language: mimeLanguage };
  return { kind: "unsupported" };
}
