// Function to create a new folder
export async function createFolder(folderName: string): Promise<number> {
  const response = await fetch("/api/folder", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ folder_name: folderName }),
  });
  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.detail || "Failed to create folder");
  }
  const data = await response.json();
  return data;
}

// Function to add a chat session to a folder
export async function addChatToFolder(
  folderId: number,
  chatSessionId: string
): Promise<void> {
  const response = await fetch(`/api/folder/${folderId}/add-chat-session`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ chat_session_id: chatSessionId }),
  });
  if (!response.ok) {
    throw new Error("Failed to add chat to folder");
  }
}

// Function to remove a chat session from a folder
export async function removeChatFromFolder(
  folderId: number,
  chatSessionId: string
): Promise<void> {
  const response = await fetch(`/api/folder/${folderId}/remove-chat-session`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ chat_session_id: chatSessionId }),
  });
  if (!response.ok) {
    throw new Error("Failed to remove chat from folder");
  }
}

// Function to delete a folder
export async function deleteFolder(folderId: number): Promise<void> {
  const response = await fetch(`/api/folder/${folderId}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  if (!response.ok) {
    throw new Error("Failed to delete folder");
  }
}

// Function to update a folder's name
export async function updateFolderName(
  folderId: number,
  newName: string
): Promise<void> {
  const response = await fetch(`/api/folder/${folderId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ folder_name: newName }),
  });
  if (!response.ok) {
    throw new Error("Failed to update folder name");
  }
}

// Function to update folder display priorities
export async function updateFolderDisplayPriorities(
  displayPriorityMap: Record<number, number>
): Promise<void> {
  const response = await fetch(`/api/folder/reorder`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ display_priority_map: displayPriorityMap }),
  });
  if (!response.ok) {
    throw new Error("Failed to update folder display priorities");
  }
}
