import type { ErrorResponseBody } from "@/lib/fetcher";
import type { FileUploadResponse } from "@/lib/fileConnector";

function editUrl(ccPairId: number, path: string): string {
  return `/api/manage/admin/cc-pair/${ccPairId}/edit/${path}`;
}

/** The error detail of a failed response, or its status when it has none. */
export async function errorDetailOf(response: Response): Promise<string> {
  try {
    const body: ErrorResponseBody = await response.json();
    return body.detail ?? body.message ?? `${response.status}`;
  } catch {
    return `${response.status}`;
  }
}

/**
 * Stages uploads for a file connector edit. Only an applied plan that
 * lists them indexes them. Pass the edit's metadata file id so that a
 * second zip merges into the first.
 */
export async function stageEditFiles(
  ccPairId: number,
  files: File[],
  draftZipMetadataFileId: string | null
): Promise<FileUploadResponse> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  if (draftZipMetadataFileId !== null) {
    formData.append("draft_zip_metadata_file_id", draftZipMetadataFileId);
  }
  const response = await fetch(editUrl(ccPairId, "files"), {
    method: "POST",
    body: formData,
  });
  if (!response.ok) throw new Error(await errorDetailOf(response));
  return response.json();
}
