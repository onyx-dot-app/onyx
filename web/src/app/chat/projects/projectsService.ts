import { Prompt } from "@/app/admin/assistants/interfaces";
import { ChatFileType, ChatSession } from "../interfaces";

export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  user_id: string;
  chat_sessions: ChatSession[];
}

export interface ProjectFile {
  id: string;
  name: string;
  project_id: string | number | null;
  user_id: string | null;
  file_id: string;
  created_at: string;
  status: string;
  file_type: string;
  last_accessed_at: string;
  chat_file_type: ChatFileType;
}

export type ProjectDetails = {
  project: Project;
  files?: ProjectFile[];
  instructions?: Prompt;
};

export async function fetchProjects(): Promise<Project[]> {
  const response = await fetch("/api/user/projects/");
  if (!response.ok) {
    throw new Error("Failed to fetch projects");
  }
  return response.json();
}

export async function createProject(name: string): Promise<Project> {
  const response = await fetch(
    `/api/user/projects/create?name=${encodeURIComponent(name)}`,
    { method: "POST" }
  );
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error((errorData as any).detail || "Failed to create project");
  }
  return response.json();
}

export async function uploadFiles(
  files: File[],
  projectId?: string | number | null
): Promise<ProjectFile[]> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  if (projectId !== undefined && projectId !== null) {
    formData.append("project_id", String(projectId));
  }

  const response = await fetch("/api/user/projects/file/upload", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error((errorData as any).detail || "Failed to upload files");
  }

  return response.json();
}

export async function getRecentFiles(): Promise<ProjectFile[]> {
  const response = await fetch(`/api/user/files/recent`);
  if (!response.ok) {
    throw new Error("Failed to fetch recent files");
  }
  return response.json();
}

export async function getFilesInProject(
  projectId: string
): Promise<ProjectFile[]> {
  const response = await fetch(`/api/user/projects/files/${projectId}`);
  if (!response.ok) {
    throw new Error("Failed to fetch project files");
  }
  return response.json();
}

export async function getProject(projectId: string): Promise<Project> {
  const response = await fetch(`/api/user/projects/${projectId}`);
  if (!response.ok) {
    throw new Error("Failed to fetch project");
  }
  return response.json();
}

export async function getProjectInstructions(
  projectId: string
): Promise<Prompt | null> {
  const response = await fetch(`/api/user/projects/${projectId}/instructions`);
  if (!response.ok) {
    throw new Error("Failed to fetch project instructions");
  }
  const data = await response.json();
  return data;
}

export async function upsertProjectInstructions(
  projectId: string,
  instructions: string
): Promise<Prompt> {
  const response = await fetch(`/api/user/projects/${projectId}/instructions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instructions }),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      (errorData as any).detail || "Failed to upsert project instructions"
    );
  }
  return response.json();
}

export async function getProjectDetails(
  projectId: string
): Promise<ProjectDetails> {
  const response = await fetch(`/api/user/projects/${projectId}/details`);
  if (!response.ok) {
    throw new Error("Failed to fetch project details");
  }
  return response.json();
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
    const errorData = await response.json().catch(() => ({}));
    throw new Error((errorData as any).detail || "Failed to move chat session");
  }
  return response.ok;
}
