import { File, UploadType } from "expo-file-system";

import { getBaseUrl } from "@/api/config";
import { getToken } from "@/api/auth/tokenStore";
import { ApiError } from "@/api/errors";
import type { CategorizedFiles } from "@/chat/contracts/projects";

// A picked file normalized across the document + image pickers.
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

// Must match the backend `build_hashed_file_key` + web `buildFileKey`:
// `${size}|${name[:50]}`, so the server can echo our temp_id back. Some picks
// have no size → empty segment.
export function buildFileKey(asset: NormalizedAsset): string {
  const namePrefix = asset.name.slice(0, 50);
  return `${asset.size ?? ""}|${namePrefix}`;
}

// The uploader resolves for non-2xx, so the status is checked here; a 2xx body that
// isn't the expected JSON shape is an error too.
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

// A started, cancelable upload. `cancel()` aborts the in-flight request; the epoch guard (not
// cancellation) is what guarantees a late result can't land.
export interface StartedUpload {
  result: Promise<CategorizedFiles>;
  cancel: () => void;
}

// Native multipart uploader (streams from disk). Bypasses apiFetch (bearer attached
// manually). `projectId` null → an unlinked per-message file.
export function startUpload(
  asset: NormalizedAsset,
  projectId: number | null,
  tempId: string,
  onProgress?: (ratio: number) => void,
): StartedUpload {
  const controller = new AbortController();

  const result = (async () => {
    const token = await getToken();
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
