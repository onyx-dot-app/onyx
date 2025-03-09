import { INTERNAL_URL } from "@/lib/constants";

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
