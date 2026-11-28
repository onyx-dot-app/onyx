import { buildArtifactUrl } from "@/app/craft/services/apiServices";
import { FetchError } from "@/lib/fetcher";

export type BinaryPreviewKind = "docx" | "spreadsheet" | "audio" | "video";

export function binaryPreviewKind(path: string): BinaryPreviewKind | undefined {
  if (/\.docx$/i.test(path)) return "docx";
  if (/\.(xlsx|xls|ods)$/i.test(path)) return "spreadsheet";
  if (/\.(mp3|wav|m4a|ogg|flac|aac)$/i.test(path)) return "audio";
  if (/\.(mp4|webm|mov)$/i.test(path)) return "video";
  return undefined;
}

type BinaryPreviewData =
  | { blob: Blob; tooLarge?: false }
  | { tooLarge: true; blob?: never };

/** Bound downloads even when the server omits Content-Length. */
export async function fetchBinaryPreview(
  sessionId: string,
  path: string,
  maxBytes: number
): Promise<BinaryPreviewData> {
  const response = await fetch(buildArtifactUrl(sessionId, path), {
    cache: "no-store",
  });
  if (!response.ok)
    throw new FetchError(
      `Failed to fetch preview: ${response.status}`,
      response.status,
      null
    );
  if (Number(response.headers.get("Content-Length")) > maxBytes) {
    await response.body?.cancel();
    return { tooLarge: true };
  }
  const reader = response.body?.getReader();
  if (!reader) {
    const blob = await response.blob();
    return blob.size > maxBytes ? { tooLarge: true } : { blob };
  }
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        return { tooLarge: true };
      }
      chunks.push(new Uint8Array(value));
    }
  } finally {
    reader.releaseLock();
  }
  return {
    blob: new Blob(chunks, {
      type: response.headers.get("Content-Type") || "application/octet-stream",
    }),
  };
}
