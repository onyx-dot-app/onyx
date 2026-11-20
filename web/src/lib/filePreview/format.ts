import {
  getCodeLanguage,
  getDataLanguage,
  getLanguageByMime,
  isMarkdownFile,
} from "@/lib/languages";

/** How a file previews. Code, text and data files share `code`. */
export type FilePreviewFormat =
  | { kind: "code"; language: string }
  | { kind: "markdown" }
  | { kind: "csv" }
  | { kind: "spreadsheet" }
  | { kind: "pdf" }
  | { kind: "docx" }
  | { kind: "pptx" }
  | { kind: "image" }
  | { kind: "unsupported" };

const SPREADSHEET_MIME_TYPES = [
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel.sheet.macroenabled.12",
];
const DOCX_MIME_TYPE =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const PPTX_MIME_TYPE =
  "application/vnd.openxmlformats-officedocument.presentationml.presentation";
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

/**
 * Picks a file's preview from its name and MIME type. A code, markup or data
 * extension wins over the MIME type, so HTML shows as code. SVG shows as XML
 * source: the server sends it without an image type, so it cannot load in an
 * `<img>`. Other images show by MIME type only.
 */
export function resolveFilePreviewFormat(
  fileName: string,
  mimeType: string
): FilePreviewFormat {
  const name = fileName.toLowerCase();
  const mime = mimeType.split(";")[0]?.trim().toLowerCase() ?? "";

  const codeLanguage = getCodeLanguage(name);
  if (codeLanguage) return { kind: "code", language: codeLanguage };
  if (mime === "image/svg+xml" || name.endsWith(".svg"))
    return { kind: "code", language: "xml" };
  if (mime.startsWith("image/")) return { kind: "image" };
  if (mime === "application/pdf" || name.endsWith(".pdf"))
    return { kind: "pdf" };
  if (mime === "text/csv" || name.endsWith(".csv")) return { kind: "csv" };
  if (SPREADSHEET_MIME_TYPES.includes(mime) || /\.xls[xm]$/.test(name))
    return { kind: "spreadsheet" };
  if (MARKDOWN_MIME_TYPES.includes(mime) || isMarkdownFile(name))
    return { kind: "markdown" };
  if (mime === DOCX_MIME_TYPE || name.endsWith(".docx"))
    return { kind: "docx" };
  if (mime === PPTX_MIME_TYPE || name.endsWith(".pptx"))
    return { kind: "pptx" };
  if (TEXT_EXTENSIONS.test(name))
    return { kind: "code", language: "plaintext" };
  const dataLanguage = getDataLanguage(name);
  if (dataLanguage) return { kind: "code", language: dataLanguage };
  if (TEXT_MIME_TYPES.includes(mime))
    return { kind: "code", language: "plaintext" };
  const mimeLanguage = getLanguageByMime(mime);
  if (mimeLanguage) return { kind: "code", language: mimeLanguage };
  return { kind: "unsupported" };
}
