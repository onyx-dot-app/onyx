import { File, UploadType } from "expo-file-system";

import { getBaseUrl } from "@/api/config";
import { getValidToken } from "@/api/auth/refreshState";
import { ApiError } from "@/api/errors";
import type { CategorizedFiles } from "@/chat/contracts/projects";

export interface NormalizedAsset {
  uri: string;
  name: string;
  mimeType?: string;
  size?: number;
}

let tempIdCounter = 0;

export function generateTempId(): string {
  tempIdCounter += 1;
  return `temp-${Date.now()}-${tempIdCounter}`;
}

/*
 * Must match the backend's `build_hashed_file_key` (empty segment when a pick has no size) or the
 * server can't echo our temp_id back.
 */
export function buildFileKey(asset: NormalizedAsset): string {
  const namePrefix = asset.name.slice(0, 50);
  return `${asset.size ?? ""}|${namePrefix}`;
}

// The uploader resolves for non-2xx too, so the status is checked here rather than caught.
function parseUploadResponse(status: number, body: string): CategorizedFiles {
  if (status < 200 || status >= 300) {
    throw new ApiError({ status, detail: "Failed to upload file.", body });
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    throw new ApiError({
      status,
      detail: "Upload succeeded but the response wasn't JSON.",
      body,
    });
  }
  if (
    typeof parsed !== "object" ||
    parsed === null ||
    !Array.isArray((parsed as CategorizedFiles).user_files) ||
    !Array.isArray((parsed as CategorizedFiles).rejected_files)
  ) {
    throw new ApiError({ status, detail: "Unexpected upload response.", body });
  }
  return parsed as CategorizedFiles;
}

/*
 * `cancel()` aborts the in-flight request, but it's the epoch guard — not cancellation — that
 * guarantees a late result can't land.
 */
export interface StartedUpload {
  result: Promise<CategorizedFiles>;
  cancel: () => void;
}

/*
 * Bypasses apiFetch so expo can stream the file from disk. Null `projectId` leaves the file
 * unlinked — a per-message attachment.
 */
export function startUpload(
  asset: NormalizedAsset,
  projectId: number | null,
  tempId: string,
  onProgress?: (ratio: number) => void,
): StartedUpload {
  const controller = new AbortController();

  const result = (async () => {
    const token = await getValidToken();
    const url = `${getBaseUrl()}/user/projects/file/upload`;

    const parameters: Record<string, string> = {
      temp_id_map: JSON.stringify({ [buildFileKey(asset)]: tempId }),
    };
    if (projectId != null) parameters.project_id = String(projectId);

    const raw = await new File(asset.uri).upload(url, {
      httpMethod: "POST",
      uploadType: UploadType.MULTIPART,
      fieldName: "files",
      mimeType: asset.mimeType,
      parameters,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      signal: controller.signal,
      onProgress: ({ bytesSent, totalBytes }) => {
        if (totalBytes > 0) onProgress?.(bytesSent / totalBytes);
      },
    });

    return parseUploadResponse(raw.status, raw.body);
  })();

  return { result, cancel: () => controller.abort() };
}
