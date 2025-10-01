import { INTERNAL_URL } from "@/lib/constants";

// Add this interface for the bulk cleanup
export interface BulkCleanupRequest {
  folder_id: number;
  days_older_than: number | null;
}

// Existing API functions may be here if the file already exists

export const deleteFolder = async (folderId: number): Promise<void> => {
  try {
    const response = await fetch(
      `${INTERNAL_URL}/api/user_files/folder/${folderId}`,
      {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to delete folder: ${response.statusText}`);
    }
  } catch (error) {
    console.error("Error deleting folder:", error);
    throw error;
  }
};

// Add this new function
export const bulkCleanupFiles = async (
  request: BulkCleanupRequest
): Promise<{ message: string }> => {
  try {
    const response = await fetch("/api/user/file/bulk-cleanup", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
      credentials: "include",
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("Cleanup error response:", errorText);
      throw new Error(
        `Failed to cleanup files: ${response.status} ${response.statusText}`
      );
    }

    const result = await response.json();
    return result;
  } catch (error) {
    console.error("Error cleaning up files:", error);
    throw error;
  }
};
