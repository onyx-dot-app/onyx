import mime from "mime";
import { fetchChatFile } from "@/lib/chat/svc";
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
// The most bytes a preview reads. A larger file shows a download instead.
const PREVIEW_BYTE_LIMITS = {
  text: 5 * MB,
  docx: 20 * MB,
  pptx: 20 * MB,
  pdf: 100 * MB,
};

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
        text: string;
        size: number;
        lineCount: number;
      }
    | { kind: "markdown"; text: string; size: number }
    // A CSV is one sheet, in the form the server parses a workbook into
    | { kind: "csv"; sheets: [SpreadsheetSheet] }
    | { kind: "pdf"; blob: Blob }
    | { kind: "docx" | "pptx"; bytes: Uint8Array<ArrayBuffer> }
    | { kind: "spreadsheet"; sheets: SpreadsheetSheet[] }
    | { kind: "image" | "unsupported" }
    | { kind: "tooLarge"; limitMB: number }
  );

async function loadSpreadsheet(
  fileId: string,
  identity: ChatFileIdentity,
  signal?: AbortSignal
): Promise<ChatFilePreviewData> {
  const response = await fetchChatFile(fileId, true, signal);
  const preview = parseSpreadsheetPreview(await response.text());
  if (!preview) throw new Error("The spreadsheet preview is malformed");
  return { ...identity, kind: "spreadsheet", sheets: preview.sheets };
}

/**
 * Reads `/api/chat/file/{id}` for a preview: the response names the file and
 * its type, which pick the preview. A spreadsheet previews from the server's
 * parsed sheets (`?parsed=true`), and an image or an unsupported file reads
 * no body. Other bodies are read up to their format's limit; the server
 * streams files without a length, so the limit applies while reading.
 * `signal` stops the download when the preview closes.
 */
export async function loadChatFilePreview(
  fileId: string,
  displayName: string,
  signal?: AbortSignal
): Promise<ChatFilePreviewData> {
  // A spreadsheet name skips the workbook download
  if (
    resolveFilePreviewFormat(displayName, "application/octet-stream").kind ===
    "spreadsheet"
  ) {
    return loadSpreadsheet(
      fileId,
      {
        name: displayName,
        mimeType: mime.getType(displayName) ?? "application/octet-stream",
      },
      signal
    );
  }

  const response = await fetchChatFile(fileId, false, signal);
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
  const format: FilePreviewFormat = resolveFilePreviewFormat(
    identity.name,
    mimeType
  );

  if (
    format.kind === "spreadsheet" ||
    format.kind === "image" ||
    format.kind === "unsupported"
  ) {
    await response.body?.cancel();
    return format.kind === "spreadsheet"
      ? loadSpreadsheet(fileId, identity, signal)
      : { ...identity, kind: format.kind };
  }

  const maxBytes =
    format.kind === "pdf" || format.kind === "docx" || format.kind === "pptx"
      ? PREVIEW_BYTE_LIMITS[format.kind]
      : PREVIEW_BYTE_LIMITS.text;
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
      blob: new Blob(chunks, { type: mimeType }),
    };
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }

  switch (format.kind) {
    case "docx":
    case "pptx":
      return { ...identity, kind: format.kind, bytes };
    case "code": {
      const text = new TextDecoder().decode(bytes);
      return {
        ...identity,
        kind: "code",
        language: format.language,
        text,
        size,
        lineCount: text.split("\n").length,
      };
    }
    case "markdown":
      return {
        ...identity,
        kind: "markdown",
        text: new TextDecoder().decode(bytes),
        size,
      };
    case "csv":
      return {
        ...identity,
        kind: "csv",
        sheets: [
          {
            name: identity.name,
            csv: new TextDecoder().decode(bytes),
            truncated: false,
          },
        ],
      };
  }
}
