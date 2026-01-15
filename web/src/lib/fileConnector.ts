export interface ConnectorFileInfo {
  file_id: string;
  file_name: string;
  file_size?: number;
  upload_date?: string;
}

export interface ConnectorFilesResponse {
  files: ConnectorFileInfo[];
}

export interface FileUploadResponse {
  file_paths: string[];
  file_names: string[];
  zip_metadata: Record<string, unknown>;
}

export async function updateConnectorFiles(
  connectorId: number,
  fileIdsToRemove: string[],
  filesToAdd: File[]
): Promise<void> {
  const formData = new FormData();

  // Add files to remove as JSON
  formData.append("file_ids_to_remove", JSON.stringify(fileIdsToRemove));

  // Add new files
  filesToAdd.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch(
    `/api/manage/admin/connector/${connectorId}/files/update`,
    {
      method: "POST",
      body: formData,
    }
  );

  if (!response.ok) {
    const error = await response.json();
    throw new Error(
      `Failed to update connector files (${response.status}): ${
        error.detail || "Unknown error"
      }`
    );
  }
}
