// Chat-attachment file transport: multipart upload, status polling, and the
// authed image-download URL. Mirrors web projectsService.ts (uploadFiles /
// getUserFileStatuses), but talks to the backend directly (no `/api` prefix).

import * as LegacyFileSystem from "expo-file-system/legacy";

import { resolveAuthHeadersRecord } from "./authHeaders";
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
 * Uses expo-file-system's native `uploadAsync` (MULTIPART) rather than
 * `fetch` + a hand-built FormData part. On Expo SDK 56 / RN 0.85 the WHATWG
 * `fetch` rejects the React-Native-style `{ uri, name, type }` FormData part
 * with "Unsupported FormDataPart implementation", so the upload never reached
 * the backend (no user_file record was ever created). `uploadAsync` reads the
 * `file://` URI and builds the multipart body natively, which works reliably.
 *
 * It uploads one file per request; callers (useComposerAttachments.uploadOne)
 * already upload a single file at a time, so we loop and merge results to keep
 * the array signature.
 */
export async function uploadChatFiles(
  files: UploadableFile[],
  config: ClientConfig,
  projectId?: number | null,
): Promise<CategorizedFiles> {
  const headers = await resolveAuthHeadersRecord(config);

  const url = `${config.baseUrl}${SWR_KEYS.chatFileUpload}`;
  const merged: CategorizedFiles = { user_files: [], rejected_files: [] };
  // When a projectId is given, the backend links the uploaded file to that
  // project (web `uploadFiles` appends a `project_id` form field). Omit it for
  // plain chat attachments (web parity: message files have no project).
  const parameters =
    projectId !== undefined && projectId !== null
      ? { project_id: String(projectId) }
      : undefined;

  for (const file of files) {
    const response = await LegacyFileSystem.uploadAsync(url, file.uri, {
      httpMethod: "POST",
      uploadType: LegacyFileSystem.FileSystemUploadType.MULTIPART,
      // Backend reads `files: list[UploadFile]` (projects/api.py upload_user_files).
      fieldName: "files",
      mimeType: file.mimeType,
      parameters,
      headers,
    });

    if (response.status < 200 || response.status >= 300) {
      let info: unknown = {};
      try {
        info = JSON.parse(response.body);
      } catch {
        info = response.body;
      }
      throw new FetchError(
        `Upload files failed with status ${response.status}`,
        response.status,
        info,
      );
    }

    const parsed = JSON.parse(response.body) as CategorizedFiles;
    if (parsed.user_files) merged.user_files.push(...parsed.user_files);
    if (parsed.rejected_files) merged.rejected_files.push(...parsed.rejected_files);
  }

  return merged;
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
