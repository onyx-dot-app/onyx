import { ChatFileType, ChatSession } from "../interfaces";

// Generic error handler that avoids exposing server error details
const handleRequestError = (action: string, response: Response) => {
  throw new Error(`${action} failed (Status: ${response.status})`);
};

export interface Project {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  user_id: string;
  instructions: string | null;
  chat_sessions: ChatSession[];
}

export interface CategorizedFiles {
  user_files: ProjectFile[];
  non_accepted_files: string[];
  unsupported_files: string[];
}

export interface ProjectFile {
  id: string;
  name: string;
  project_id: number | null;
  user_id: string | null;
  file_id: string;
  created_at: string;
  status: UserFileStatus;
  file_type: string;
  last_accessed_at: string;
  chat_file_type: ChatFileType;
  token_count: number | null;
  chunk_count: number | null;
  temp_id?: string | null;
}

export interface UserFileDeleteResult {
  has_associations: boolean;
  project_names: string[];
  assistant_names: string[];
}

export enum UserFileStatus {
  UPLOADING = "UPLOADING", //UI only
  PROCESSING = "PROCESSING",
  COMPLETED = "COMPLETED",
  FAILED = "FAILED",
  CANCELED = "CANCELED",
  DELETING = "DELETING",
}

export type ProjectDetails = {
  project: Project;
  files?: ProjectFile[];
  persona_id_to_is_default?: Record<number, boolean>;
};

export async function fetchProjects(): Promise<Project[]> {
  const response = await fetch("/api/user/projects/");
  if (!response.ok) {
    handleRequestError("Fetch projects", response);
  }
  return response.json();
}

export async function createProject(name: string): Promise<Project> {
  const response = await fetch(
    `/api/user/projects/create?name=${encodeURIComponent(name)}`,
    { method: "POST" }
  );
  if (!response.ok) {
    handleRequestError("Create project", response);
  }
  return response.json();
}

export async function uploadFiles(
  files: File[],
  projectId?: number | null,
  tempIdMap?: Map<string, string>
): Promise<CategorizedFiles> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  if (projectId !== undefined && projectId !== null) {
    formData.append("project_id", String(projectId));
  }
  if (tempIdMap !== undefined && tempIdMap !== null) {
    formData.append(
      "temp_id_map",
      JSON.stringify(Object.fromEntries(tempIdMap))
    );
  }

  const response = await fetch("/api/user/projects/file/upload", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    handleRequestError("Upload files", response);
  }

  return response.json();
}

export async function getRecentFiles(): Promise<ProjectFile[]> {
  const response = await fetch(`/api/user/files/recent`);
  if (!response.ok) {
    handleRequestError("Fetch recent files", response);
  }
  return response.json();
}

export async function getFilesInProject(
  projectId: number
): Promise<ProjectFile[]> {
  const response = await fetch(`/api/user/projects/files/${projectId}`);
  if (!response.ok) {
    handleRequestError("Fetch project files", response);
  }
  return response.json();
}

export async function getProject(projectId: number): Promise<Project> {
  const response = await fetch(`/api/user/projects/${projectId}`);
  if (!response.ok) {
    handleRequestError("Fetch project", response);
  }
  return response.json();
}

export async function renameProject(
  projectId: number,
  name: string
): Promise<Project> {
  const response = await fetch(`/api/user/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    handleRequestError("Rename project", response);
  }
  return response.json();
}

export async function deleteProject(projectId: number): Promise<void> {
  const response = await fetch(`/api/user/projects/${projectId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    handleRequestError("Delete project", response);
  }
}

export async function getProjectInstructions(
  projectId: number
): Promise<string | null> {
  const response = await fetch(`/api/user/projects/${projectId}/instructions`);
  if (!response.ok) {
    handleRequestError("Fetch project instructions", response);
  }
  const data = (await response.json()) as { instructions: string | null };
  return data.instructions ?? null;
}

export async function upsertProjectInstructions(
  projectId: number,
  instructions: string
): Promise<string | null> {
  const response = await fetch(`/api/user/projects/${projectId}/instructions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instructions }),
  });
  if (!response.ok) {
    handleRequestError("Update project instructions", response);
  }
  const data = (await response.json()) as { instructions: string | null };
  return data.instructions ?? null;
}

export async function getProjectDetails(
  projectId: number
): Promise<ProjectDetails> {
  const response = await fetch(`/api/user/projects/${projectId}/details`);
  if (!response.ok) {
    handleRequestError("Fetch project details", response);
  }
  return response.json();
}

export async function unlinkFileFromProject(
  projectId: number,
  fileId: string
): Promise<Response> {
  const response = await fetch(
    `/api/user/projects/${encodeURIComponent(
      projectId
    )}/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    handleRequestError("Unlink file from project", response);
  }
  return response;
}

export async function linkFileToProject(
  projectId: number,
  fileId: string
): Promise<Response> {
  const response = await fetch(
    `/api/user/projects/${encodeURIComponent(
      projectId
    )}/files/${encodeURIComponent(fileId)}`,
    { method: "POST" }
  );
  if (!response.ok) {
    handleRequestError("Link file to project", response);
  }
  return response;
}

export async function deleteUserFile(
  fileId: string
): Promise<UserFileDeleteResult> {
  const response = await fetch(
    `/api/user/projects/file/${encodeURIComponent(fileId)}`,
    {
      method: "DELETE",
    }
  );
  if (!response.ok) {
    handleRequestError("Delete file", response);
  }
  return (await response.json()) as UserFileDeleteResult;
}

export async function getUserFile(fileId: string): Promise<ProjectFile> {
  const response = await fetch(
    `/api/user/projects/file/${encodeURIComponent(fileId)}`
  );
  if (!response.ok) {
    handleRequestError("Fetch file", response);
  }
  return response.json();
}

export async function getUserFileStatuses(
  fileIds: string[]
): Promise<ProjectFile[]> {
  const response = await fetch(`/api/user/projects/file/statuses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_ids: fileIds }),
  });
  if (!response.ok) {
    handleRequestError("Fetch file statuses", response);
  }
  return response.json();
}

export async function getSessionProjectTokenCount(
  chatSessionId: string
): Promise<number> {
  const response = await fetch(
    `/api/user/projects/session/${encodeURIComponent(
      chatSessionId
    )}/token-count`
  );
  if (!response.ok) {
    return 0;
  }
  const data = (await response.json()) as { total_tokens: number };
  return data.total_tokens ?? 0;
}

export async function getProjectFilesForSession(
  chatSessionId: string
): Promise<ProjectFile[]> {
  const response = await fetch(
    `/api/user/projects/session/${encodeURIComponent(chatSessionId)}/files`
  );
  if (!response.ok) {
    return [];
  }
  return response.json();
}

export async function getProjectTokenCount(projectId: number): Promise<number> {
  const response = await fetch(
    `/api/user/projects/${encodeURIComponent(projectId)}/token-count`
  );
  if (!response.ok) {
    return 0;
  }
  const data = (await response.json()) as { total_tokens: number };
  return data.total_tokens ?? 0;
}

export async function getMaxSelectedDocumentTokens(
  personaId: number
): Promise<number> {
  const response = await fetch(
    `/api/chat/max-selected-document-tokens?persona_id=${personaId}`
  );
  if (!response.ok) {
    return 128_000;
  }
  const json = await response.json();
  return (json?.max_tokens as number) ?? 128_000;
}

export async function moveChatSession(
  projectId: number,
  chatSessionId: string
): Promise<boolean> {
  const response = await fetch(
    `/api/user/projects/${projectId}/move_chat_session`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_session_id: chatSessionId }),
    }
  );
  if (!response.ok) {
    handleRequestError("Move chat session", response);
  }
  return response.ok;
}

export async function removeChatSessionFromProject(
  chatSessionId: string
): Promise<boolean> {
  const response = await fetch(`/api/user/projects/remove_chat_session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_session_id: chatSessionId }),
  });
  if (!response.ok) {
    handleRequestError("Remove chat session from project", response);
  }
  return response.ok;
}
