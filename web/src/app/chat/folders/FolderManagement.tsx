import { useState, useEffect, FC } from "react";

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
    throw new Error("Failed to create folder");
  }
  const data = await response.json();
  return data.folder_id;
}

// Function to add a chat session to a folder
export async function addChatToFolder(
  folderId: number,
  chatSessionId: number
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
  chatSessionId: number
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
