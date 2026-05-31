// Chat-attachment file transport: multipart upload, status polling, and the
// authed image-download URL. Mirrors the web `uploadFiles` /
// `getUserFileStatuses` (web/src/app/app/projects/projectsService.ts) against the
// same backend routes — but talks to the backend directly (no `/api` prefix).

import { errorHandlingFetcher } from "./fetcher";
import { FetchError } from "./errors";
import type { ClientConfig } from "./config";
import { SWR_KEYS } from "./endpoints";
import type { CategorizedFiles, ProjectFile } from "@/lib/types";

/** A locally-picked file ready to upload (from expo-image-picker / -document-picker). */
export interface UploadableFile {
  /** Local file URI (`file://…` / `ph://…`). */
  uri: string;
  /** Filename incl. extension — the backend keys `chat_file_type` off it. */
  name: string;
  /** MIME type when the picker reports one. */
  mimeType?: string;
}

/** Absolute, authenticated URL for an uploaded file's bytes (image previews). */
export function chatFileUrl(baseUrl: string, fileId: string): string {
  return `${baseUrl}/chat/file/${encodeURIComponent(fileId)}`;
}

/**
 * Upload picked files as `multipart/form-data` to `/user/projects/file/upload`
 * and return the categorized result. Message-only files are uploaded with no
 * `project_id` (web parity).
 *
 * Uses the RN global `fetch` rather than `config.fetchImpl` (expo/fetch): the
 * global fetch is the reliable path for multipart `{ uri, name, type }` file
 * parts on React Native. `Content-Type` is intentionally NOT set so the runtime
 * fills in the `multipart/form-data; boundary=…` header itself.
 */
export async function uploadChatFiles(
  files: UploadableFile[],
  config: ClientConfig,
): Promise<CategorizedFiles> {
  const formData = new FormData();
  for (const file of files) {
    // RN FormData accepts a `{ uri, name, type }` object for file parts; the
    // typed DOM FormData signature doesn't know about it, hence the cast.
    formData.append("files", {
      uri: file.uri,
      name: file.name,
      type: file.mimeType ?? "application/octet-stream",
    } as unknown as Blob);
  }

  const headers = new Headers();
  new Headers(await config.getAuthHeaders()).forEach((value, key) => {
    headers.set(key, value);
  });

  const response = await fetch(`${config.baseUrl}${SWR_KEYS.chatFileUpload}`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!response.ok) {
    const info = await response.json().catch(() => ({}));
    throw new FetchError(
      `Upload files failed with status ${response.status}`,
      response.status,
      info,
    );
  }

  return (await response.json()) as CategorizedFiles;
}

/**
 * Fetch the latest status of the given uploaded files
 * (`POST /user/projects/file/statuses`). Polled by the composer until every
 * tracked file reaches a terminal status.
 */
export async function fetchFileStatuses(
  fileIds: string[],
  config: ClientConfig,
): Promise<ProjectFile[]> {
  return errorHandlingFetcher<ProjectFile[]>(
    SWR_KEYS.chatFileStatuses,
    config,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_ids: fileIds }),
    },
  );
}
