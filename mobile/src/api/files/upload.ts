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

// Native multipart uploader: streams from disk (no FormData memory spike) and
// reports byte progress. Bypasses apiFetch, so the bearer is attached manually;
// it resolves for non-2xx, so status is checked.
export async function uploadProjectFile(
  asset: NormalizedAsset,
  projectId: number,
  tempId: string,
  onProgress?: (ratio: number) => void,
): Promise<CategorizedFiles> {
  const token = await getToken();
  const url = `${getBaseUrl()}/user/projects/file/upload`;

  const result = await new File(asset.uri).upload(url, {
    httpMethod: "POST",
    uploadType: UploadType.MULTIPART,
    fieldName: "files",
    mimeType: asset.mimeType,
    parameters: {
      project_id: String(projectId),
      temp_id_map: JSON.stringify({ [buildFileKey(asset)]: tempId }),
    },
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    onProgress: ({ bytesSent, totalBytes }) => {
      if (totalBytes > 0) onProgress?.(bytesSent / totalBytes);
    },
  });

  if (result.status < 200 || result.status >= 300) {
    throw new ApiError({
      status: result.status,
      detail: "Failed to upload file.",
      body: result.body,
    });
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(result.body);
  } catch {
    throw new ApiError({
      status: result.status,
      detail: "Upload succeeded but the response wasn't JSON.",
      body: result.body,
    });
  }
  if (
    typeof parsed !== "object" ||
    parsed === null ||
    !Array.isArray((parsed as CategorizedFiles).user_files) ||
    !Array.isArray((parsed as CategorizedFiles).rejected_files)
  ) {
    throw new ApiError({
      status: result.status,
      detail: "Unexpected upload response.",
      body: result.body,
    });
  }
  return parsed as CategorizedFiles;
}
