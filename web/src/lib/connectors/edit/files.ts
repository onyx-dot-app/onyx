import type { FileUploadResponse } from "@/lib/fileConnector";

/** The files of a file connector, as its config lists them. */
export interface ConnectorFileList {
  fileIds: string[];
  /** One display name per file id. */
  fileNames: string[];
}

/** The stored list, with a name for every file (the id when none is stored). */
export function storedFileList(
  fileLocations: readonly string[],
  fileNames: readonly string[] | null
): ConnectorFileList {
  return {
    fileIds: [...fileLocations],
    fileNames: fileLocations.map(
      (fileId, index) => fileNames?.[index] ?? fileId
    ),
  };
}

/**
 * Adds staged files to the list. Staging returns the id of a current file
 * for an identical upload; such an id is not listed twice.
 */
export function withStagedFiles(
  list: ConnectorFileList,
  staged: Pick<FileUploadResponse, "file_paths" | "file_names">
): ConnectorFileList {
  const fileIds = [...list.fileIds];
  const fileNames = [...list.fileNames];
  staged.file_paths.forEach((fileId, index) => {
    if (fileIds.includes(fileId)) return;
    fileIds.push(fileId);
    fileNames.push(staged.file_names[index] ?? fileId);
  });
  return { fileIds, fileNames };
}

export function withoutFile(
  list: ConnectorFileList,
  fileId: string
): ConnectorFileList {
  const index = list.fileIds.indexOf(fileId);
  if (index === -1) return list;
  return {
    fileIds: list.fileIds.filter((_, position) => position !== index),
    fileNames: list.fileNames.filter((_, position) => position !== index),
  };
}
