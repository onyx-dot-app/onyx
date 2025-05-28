import {
  FileResponse,
  FolderResponse,
} from "@/app/chat/my-documents/DocumentsContext";

export async function fetchFolders(): Promise<FolderResponse[]> {
  const response = await fetch("/api/user/folder");
  if (!response.ok) {
    throw new Error("Failed to fetch folders");
  }
  return response.json();
}

export async function createNewFolder(
  name: string,
  description: string
): Promise<FolderResponse> {
  const response = await fetch("/api/user/folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.detail || "Failed to create folder");
  }
  return response.json();
}

export async function deleteFolder(folderId: number): Promise<void> {
  const response = await fetch(`/api/user/folder/${folderId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error("Failed to delete folder");
  }
}

export async function deleteFile(fileId: number): Promise<void> {
  const response = await fetch(`/api/user/file/${fileId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error("Failed to delete file");
  }
}

export async function createFileFromLinkRequest(
  url: string,
  folderId: number | null
): Promise<FileResponse[]> {
  const response = await fetch("/api/user/file/create-from-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, folder_id: folderId }),
  });
  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.detail || "Failed to create file from link");
  }
  return response.json();
}

export async function getFolderDetails(
  folderId: number
): Promise<FolderResponse> {
  const response = await fetch(`/api/user/folder/${folderId}`);
  if (!response.ok) {
    throw new Error("Failed to fetch folder details");
  }
  return response.json();
}

export async function updateFolderDetails(
  folderId: number,
  name: string,
  description: string
): Promise<void> {
  const response = await fetch(`/api/user/folder/${folderId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
  if (!response.ok) {
    throw new Error("Failed to update folder details");
  }
}

export async function moveItem(
  itemId: number,
  newFolderId: number | null,
  isFolder: boolean
): Promise<void> {
  const endpoint = isFolder
    ? `/api/user/folder/${itemId}/move`
    : `/api/user/file/${itemId}/move`;
  const response = await fetch(endpoint, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_folder_id: newFolderId }),
  });
  if (!response.ok) {
    throw new Error("Failed to move item");
  }
}

export async function renameItem(
  itemId: number,
  newName: string,
  isFolder: boolean
): Promise<void> {
  if (isFolder) {
    const response = await fetch(`/api/user/folder/${itemId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName }),
    });
    if (!response.ok) {
      throw new Error("Failed to rename folder");
    }
  } else {
    const endpoint = `/api/user/file/${itemId}/rename?name=${encodeURIComponent(
      newName
    )}`;
    const response = await fetch(endpoint, { method: "PUT" });
    if (!response.ok) {
      throw new Error("Failed to rename file");
    }
  }
}

export async function downloadItem(documentId: string): Promise<Blob> {
  const fileId = documentId.split("__")[1] || documentId;
  const response = await fetch(`/api/chat/file/${encodeURIComponent(fileId)}`, {
    method: "GET",
  });
  if (!response.ok) {
    throw new Error("Failed to fetch file");
  }
  return response.blob();
}
