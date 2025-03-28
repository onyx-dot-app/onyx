import {
  FileResponse,
  FolderResponse,
} from "@/app/chat/my-documents/DocumentsContext";

export interface AssistantFileChanges {
  filesToShare: number[];
  filesToUnshare: number[];
  foldersToShare: number[];
  foldersToUnshare: number[];
}

export function calculateFileChanges(
  existingFileIds: number[],
  existingFolderIds: number[],
  selectedFiles: FileResponse[],
  selectedFolders: FolderResponse[]
): AssistantFileChanges {
  const selectedFileIds = selectedFiles.map((file) => file.id);
  const selectedFolderIds = selectedFolders.map((folder) => folder.id);

  return {
    filesToShare: selectedFileIds.filter((id) => !existingFileIds.includes(id)),
    filesToUnshare: existingFileIds.filter(
      (id) => !selectedFileIds.includes(id)
    ),
    foldersToShare: selectedFolderIds.filter(
      (id) => !existingFolderIds.includes(id)
    ),
    foldersToUnshare: existingFolderIds.filter(
      (id) => !selectedFolderIds.includes(id)
    ),
  };
}

export async function shareFiles(
  assistantId: number,
  fileIds: number[]
): Promise<void> {
  for (const fileId of fileIds) {
    await fetch(`/api/user/file/${fileId}/share`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ assistant_id: assistantId }),
    });
  }
}

export async function unshareFiles(
  assistantId: number,
  fileIds: number[]
): Promise<void> {
  for (const fileId of fileIds) {
    await fetch(`/api/user/file/${fileId}/unshare`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ assistant_id: assistantId }),
    });
  }
}

export async function shareFolders(
  assistantId: number,
  folderIds: number[]
): Promise<void> {
  for (const folderId of folderIds) {
    await fetch(`/api/user/folder/${folderId}/share`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ assistant_id: assistantId }),
    });
  }
}

export async function unshareFolders(
  assistantId: number,
  folderIds: number[]
): Promise<void> {
  for (const folderId of folderIds) {
    await fetch(`/api/user/folder/${folderId}/unshare`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ assistant_id: assistantId }),
    });
  }
}

export async function updateAssistantFiles(
  assistantId: number,
  changes: AssistantFileChanges
): Promise<void> {
  await Promise.all([
    shareFiles(assistantId, changes.filesToShare),
    unshareFiles(assistantId, changes.filesToUnshare),
    shareFolders(assistantId, changes.foldersToShare),
    unshareFolders(assistantId, changes.foldersToUnshare),
  ]);
}
