import mime from "mime";
import { fetchChatFile } from "@/lib/chat/svc";
import { FetchError } from "@/lib/fetcher";
import { parseSpreadsheetPreview } from "@/lib/csv";
import type { SpreadsheetSheet } from "@/lib/types";
import {
  resolveFilePreviewFormat,
  type FilePreviewFormat,
} from "@/lib/filePreview/format";
import {
  parseContentDispositionFileName,
  withMimeTypeExtension,
} from "@/lib/filePreview/fileName";

const MB = 1024 * 1024;
// The most bytes a preview of a stored file reads. A larger file shows a
// download instead.
const PREVIEW_BYTE_LIMITS = {
  text: 5 * MB,
  pdf: 100 * MB,
};

// The server cannot make a PDF of a Word or PowerPoint file
const PREVIEW_UNAVAILABLE_ERROR_CODE = "PREVIEW_UNAVAILABLE";
// The server has not stored a PDF of the file yet, and can make one
const PREVIEW_NOT_READY_ERROR_CODE = "PREVIEW_NOT_READY";

interface ChatFileIdentity {
  // The stored name from the response, with an extension for its MIME type
  name: string;
  mimeType: string;
}

/** A chat file, loaded for its preview. */
export type ChatFilePreviewData = ChatFileIdentity &
  (
    | {
        kind: "code";
        language: string;
        render?: "html" | "svg";
        text: string;
        size: number;
        lineCount: number;
      }
    | { kind: "markdown"; text: string; size: number }
    // A CSV is one sheet, in the form the server parses a workbook into
    | { kind: "csv"; sheets: [SpreadsheetSheet] }
    | { kind: "pdf"; blob: Blob }
    | { kind: "spreadsheet"; sheets: SpreadsheetSheet[] }
    // `unavailable`: the server has no preview of the file
    | { kind: "image" | "unsupported" | "unavailable" }
    | { kind: "tooLarge"; limitMB: number }
  );

type BodyFormat = Extract<
  FilePreviewFormat,
  { kind: "code" | "markdown" | "csv" | "pdf" }
>;

/**
 * Loads the preview that the server makes of a file: a spreadsheet's parsed
 * sheets, or a Word or PowerPoint file as a PDF. The stored PDF loads when
 * there is one; otherwise the server converts the file first.
 */
async function loadServerPreview(
  fileId: string,
  kind: "spreadsheet" | "office",
  identity: ChatFileIdentity,
  signal?: AbortSignal
): Promise<ChatFilePreviewData> {
  if (kind === "spreadsheet") {
    const response = await fetchChatFile(fileId, "parsed", signal);
    const preview = parseSpreadsheetPreview(await response.text());
    if (!preview) throw new Error("The spreadsheet preview is malformed");
    return { ...identity, kind: "spreadsheet", sheets: preview.sheets };
  }
  try {
    const response = await fetchChatFile(fileId, "pdf", signal).catch(
      (error: unknown) => {
        if (
          error instanceof FetchError &&
          error.info?.error_code === PREVIEW_NOT_READY_ERROR_CODE
        )
          return fetchChatFile(fileId, "convertPdf", signal);
        throw error;
      }
    );
    return await readBody(
      response,
      identity,
      { kind: "pdf" },
      PREVIEW_BYTE_LIMITS.pdf
    );
  } catch (error) {
    if (
      error instanceof FetchError &&
      error.info?.error_code === PREVIEW_UNAVAILABLE_ERROR_CODE
    )
      return { ...identity, kind: "unavailable" };
    throw error;
  }
}

/**
 * Reads a preview's body up to `maxBytes`; the server streams files without
 * a length, so the limit applies while reading.
 */
async function readBody(
  response: Response,
  identity: ChatFileIdentity,
  format: BodyFormat,
  maxBytes: number
): Promise<ChatFilePreviewData> {
  const tooLarge: ChatFilePreviewData = {
    ...identity,
    kind: "tooLarge",
    limitMB: maxBytes / MB,
  };
  if (Number(response.headers.get("Content-Length")) > maxBytes) {
    await response.body?.cancel();
    return tooLarge;
  }
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  // An empty response has no body
  const reader = response.body?.getReader();
  if (reader) {
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > maxBytes) {
          await reader.cancel();
          return tooLarge;
        }
        chunks.push(value);
      }
    } finally {
      reader.releaseLock();
    }
  }
  // PDF.js takes ownership of an ArrayBuffer it is given, so a PDF stays a
  // Blob, built from the chunks without a joined copy
  if (format.kind === "pdf")
    return {
      ...identity,
      kind: "pdf",
      blob: new Blob(chunks, { type: "application/pdf" }),
    };
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const text = new TextDecoder().decode(bytes);

  switch (format.kind) {
    case "code":
      return {
        ...identity,
        kind: "code",
        language: format.language,
        render: format.render,
        text,
        size,
        lineCount: text.split("\n").length,
      };
    case "markdown":
      return { ...identity, kind: "markdown", text, size };
    case "csv":
      return {
        ...identity,
        kind: "csv",
        sheets: [{ name: identity.name, csv: text, truncated: false }],
      };
  }
}

/**
 * Reads `/api/chat/file/{id}` for a preview: the response names the file and
 * its type, which pick the preview. A spreadsheet previews from the server's
 * parsed sheets, and a Word or PowerPoint file from the PDF the server
 * converts it to; a name in one of these formats skips the original's
 * download. An image or an unsupported file reads no body. `signal` stops
 * the download when the preview closes.
 */
export async function loadChatFilePreview(
  fileId: string,
  displayName: string,
  signal?: AbortSignal
): Promise<ChatFilePreviewData> {
  const named = resolveFilePreviewFormat(
    displayName,
    "application/octet-stream"
  );
  if (named.kind === "spreadsheet" || named.kind === "office") {
    return loadServerPreview(
      fileId,
      named.kind,
      {
        name: displayName,
        mimeType: mime.getType(displayName) ?? "application/octet-stream",
      },
      signal
    );
  }

  const response = await fetchChatFile(fileId, "original", signal);
  const storedName =
    parseContentDispositionFileName(
      response.headers.get("Content-Disposition")
    ) ?? displayName;
  const contentType =
    response.headers.get("Content-Type") || "application/octet-stream";
  const mimeType =
    contentType === "application/octet-stream"
      ? (mime.getType(storedName) ?? contentType)
      : contentType;
  const identity: ChatFileIdentity = {
    name: withMimeTypeExtension(storedName, mimeType),
    mimeType,
  };
  const format = resolveFilePreviewFormat(identity.name, mimeType);

  switch (format.kind) {
    case "spreadsheet":
    case "office":
      await response.body?.cancel();
      return loadServerPreview(fileId, format.kind, identity, signal);
    case "image":
    case "unsupported":
      await response.body?.cancel();
      return { ...identity, kind: format.kind };
    default:
      return readBody(
        response,
        identity,
        format,
        format.kind === "pdf"
          ? PREVIEW_BYTE_LIMITS.pdf
          : PREVIEW_BYTE_LIMITS.text
      );
  }
}
