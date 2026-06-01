// Chat-attachment file transport: multipart upload, status polling, authed download URL.
// Mirrors web projectsService.ts (uploadFiles / getUserFileStatuses).

import * as LegacyFileSystem from "expo-file-system/legacy";

import { resolveAuthHeadersRecord } from "./authHeaders";
import { errorHandlingFetcher } from "./fetcher";
import { FetchError } from "./errors";
import type { ClientConfig } from "./config";
import { SWR_KEYS } from "./endpoints";
import type { CategorizedFiles, ProjectFile } from "@/lib/types";

// A locally-picked file ready to upload (from expo-image/-document-picker).
export interface UploadableFile {
  uri: string;
  // Filename incl. extension — the backend keys `chat_file_type` off it.
  name: string;
  mimeType?: string;
}

export function chatFileUrl(baseUrl: string, fileId: string): string {
  return `${baseUrl}/chat/file/${encodeURIComponent(fileId)}`;
}

// Upload picked files as multipart/form-data to /user/projects/file/upload.
//
// Uses expo-file-system's native `uploadAsync` rather than `fetch` + a hand-built
// FormData part: on Expo SDK 56 / RN 0.85 WHATWG `fetch` rejects the RN-style
// `{ uri, name, type }` part ("Unsupported FormDataPart implementation"), so the
// upload silently never reached the backend. uploadAsync builds the body natively.
// One file per request, so we loop and merge to keep the array signature.
export async function uploadChatFiles(
  files: UploadableFile[],
  config: ClientConfig,
  projectId?: number | null,
): Promise<CategorizedFiles> {
  const headers = await resolveAuthHeadersRecord(config);

  const url = `${config.baseUrl}${SWR_KEYS.chatFileUpload}`;
  const merged: CategorizedFiles = { user_files: [], rejected_files: [] };
  // A projectId links the upload to that project; omit it for plain chat
  // attachments (web parity: message files have no project).
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

// Polled by the composer until every tracked file reaches a terminal status.
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
