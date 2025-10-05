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

export async function listConnectorFiles(
  connectorId: number
): Promise<ConnectorFilesResponse> {
  const response = await fetch(
    `/api/manage/admin/connector/${connectorId}/files`
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(
      `Failed to list connector files (${response.status}): ${error.detail || "Unknown error"}`
    );
  }
  return await response.json();
}

export async function addFilesToConnector(
  connectorId: number,
  files: File[]
): Promise<void> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch(
    `/api/manage/admin/connector/${connectorId}/files/add`,
    {
      method: "POST",
      body: formData,
    }
  );

  if (!response.ok) {
    const error = await response.json();
    throw new Error(
      `Failed to add files to connector (${response.status}): ${error.detail || "Unknown error"}`
    );
  }
}

export async function removeFilesFromConnector(
  connectorId: number,
  fileIds: string[]
): Promise<void> {
  const response = await fetch(
    `/api/manage/admin/connector/${connectorId}/files/remove`,
    {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ file_ids: fileIds }),
    }
  );

  if (!response.ok) {
    const error = await response.json();
    throw new Error(
      `Failed to remove files from connector (${response.status}): ${error.detail || "Unknown error"}`
    );
  }
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
      `Failed to update connector files (${response.status}): ${error.detail || "Unknown error"}`
    );
  }
}
