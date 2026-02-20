import {
  ApiSessionResponse,
  ApiDetailedSessionResponse,
  ApiMessageResponse,
  ApiArtifactResponse,
  ApiUsageLimitsResponse,
  ApiWebappInfoResponse,
  SessionHistoryItem,
  Artifact,
  BuildMessage,
  StreamPacket,
  UsageLimits,
  DirectoryListing,
  SharingScope,
} from "@/app/craft/types/streamingTypes";

// =============================================================================
// API Configuration
// =============================================================================

const API_BASE = "/api/build";
export const USAGE_LIMITS_ENDPOINT = `${API_BASE}/limit`;

// =============================================================================
// SSE Stream Processing
// =============================================================================

export async function processSSEStream(
  response: Response,
  onPacket: (packet: StreamPacket) => void
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";
  let currentEventType = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("event: ") || line.startsWith("event:")) {
        // Capture the event type from the SSE event line
        currentEventType = line.slice(line.indexOf(":") + 1).trim();
      } else if (line.startsWith("data: ") || line.startsWith("data:")) {
        const dataStr = line.slice(line.indexOf(":") + 1).trim();
        if (dataStr) {
          try {
            const data = JSON.parse(dataStr);
            // The backend sends `event: message` for all events and puts the
            // actual type in data.type. Only use SSE event type as fallback
            // if data.type is not present and SSE event is not "message".
            if (
              !data.type &&
              currentEventType &&
              currentEventType !== "message"
            ) {
              onPacket({ ...data, type: currentEventType });
            } else {
              onPacket(data);
            }
          } catch (e) {
            console.error("[SSE] Parse error:", e, "Raw data:", dataStr);
          }
        }
        // Reset event type for next event
        currentEventType = "";
      }
    }
  }
}

// =============================================================================
// Session API
// =============================================================================

export interface CreateSessionOptions {
  name?: string | null;
  demoDataEnabled?: boolean;
  userWorkArea?: string | null;
  userLevel?: string | null;
  // LLM selection from user's cookie
  llmProviderType?: string | null; // Provider type (e.g., "anthropic", "openai")
  llmModelName?: string | null;
}

export async function createSession(
  options?: CreateSessionOptions
): Promise<ApiDetailedSessionResponse> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: options?.name || null,
      demo_data_enabled: options?.demoDataEnabled ?? true,
      user_work_area: options?.userWorkArea || null,
      user_level: options?.userLevel || null,
      llm_provider_type: options?.llmProviderType || null,
      llm_model_name: options?.llmModelName || null,
    }),
  });

  if (!res.ok) {
    throw new Error(`Failed to create session: ${res.status}`);
  }

  return res.json();
}

export async function fetchSession(
  sessionId: string
): Promise<ApiDetailedSessionResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`);

  if (!res.ok) {
    throw new Error(`Failed to load session: ${res.status}`);
  }

  return res.json();
}

export async function fetchSessionHistory(): Promise<SessionHistoryItem[]> {
  const res = await fetch(`${API_BASE}/sessions`);

  if (!res.ok) {
    throw new Error(`Failed to fetch session history: ${res.status}`);
  }

  const data = await res.json();
  return data.sessions.map((s: ApiSessionResponse) => ({
    id: s.id,
    title: s.name || `Session ${s.id.slice(0, 8)}...`,
    createdAt: new Date(s.created_at),
  }));
}

export async function generateSessionName(sessionId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/generate-name`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    throw new Error(`Failed to generate session name: ${res.status}`);
  }

  const data = await res.json();
  return data.name;
}

export interface SuggestionBubble {
  theme: "add" | "question";
  text: string;
}

export async function generateFollowupSuggestions(
  sessionId: string,
  userMessage: string,
  assistantMessage: string
): Promise<SuggestionBubble[]> {
  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/generate-suggestions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_message: userMessage,
        assistant_message: assistantMessage,
      }),
    }
  );

  if (!res.ok) {
    throw new Error(`Failed to generate suggestions: ${res.status}`);
  }

  const data = await res.json();
  return data.suggestions;
}

export async function updateSessionName(
  sessionId: string,
  name: string | null
): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/name`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });

  if (!res.ok) {
    throw new Error(`Failed to update session name: ${res.status}`);
  }
}

export async function setSessionSharing(
  sessionId: string,
  sharingScope: SharingScope
): Promise<{ session_id: string; sharing_scope: SharingScope }> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/public`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sharing_scope: sharingScope }),
  });

  if (!res.ok) {
    throw new Error(`Failed to update session sharing: ${res.status}`);
  }

  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: "DELETE",
  });

  if (!res.ok) {
    throw new Error(`Failed to delete session: ${res.status}`);
  }
}

/**
 * Restore a sleeping sandbox and load the session's snapshot.
 * This is a blocking call that waits until the restore is complete.
 *
 * Handles two cases:
 * 1. Sandbox is SLEEPING: Re-provisions pod, then loads session snapshot
 * 2. Sandbox is RUNNING but session not loaded: Just loads session snapshot
 *
 * Returns immediately if session workspace already exists in pod.
 */
export async function restoreSession(
  sessionId: string
): Promise<ApiDetailedSessionResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to restore session: ${res.status}`
    );
  }

  return res.json();
}

/**
 * Check if a pre-provisioned session is still valid (empty).
 * Used for polling to detect when another tab has used the session.
 *
 * @returns { valid: true, session_id: string } if session is still empty
 * @returns { valid: false, session_id: null } if session has messages or doesn't exist
 */
export async function checkPreProvisionedSession(
  sessionId: string
): Promise<{ valid: boolean; session_id: string | null }> {
  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/pre-provisioned-check`
  );

  if (!res.ok) {
    // Treat errors as invalid session
    return { valid: false, session_id: null };
  }

  return res.json();
}

// =============================================================================
// Messages API
// =============================================================================

/**
 * Extract text content from message_metadata.
 * For user_message: {type: "user_message", content: {type: "text", text: "..."}}
 */
function extractContentFromMetadata(
  metadata: Record<string, any> | null | undefined
): string {
  if (!metadata) return "";
  const content = metadata.content;
  if (!content) return "";
  if (typeof content === "string") return content;
  if (typeof content === "object" && content.type === "text" && content.text) {
    return content.text;
  }
  return "";
}

export async function fetchMessages(
  sessionId: string
): Promise<BuildMessage[]> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);

  if (!res.ok) {
    throw new Error(`Failed to fetch messages: ${res.status}`);
  }

  const data = await res.json();
  return data.messages.map((m: ApiMessageResponse) => ({
    id: m.id,
    type: m.type,
    // Content is stored in message_metadata, not as a separate field
    content: m.content || extractContentFromMetadata(m.message_metadata),
    message_metadata: m.message_metadata,
    timestamp: new Date(m.created_at),
  }));
}

/**
 * Custom error class for rate limit (429) errors.
 * Used to distinguish rate limit errors from other API errors
 * so the UI can show an upsell modal instead of a generic error.
 */
export class RateLimitError extends Error {
  public readonly statusCode: number = 429;

  constructor() {
    super("Rate limit exceeded");
    this.name = "RateLimitError";
  }
}

/**
 * Send a message and return the streaming response.
 * The caller is responsible for processing the SSE stream.
 */
export async function sendMessageStream(
  sessionId: string,
  content: string,
  signal?: AbortSignal
): Promise<Response> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/send-message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
    signal,
  });

  if (!res.ok) {
    // Handle rate limit errors specifically so UI can show upsell modal
    if (res.status === 429) {
      throw new RateLimitError();
    }
    throw new Error(`Failed to send message: ${res.status}`);
  }

  return res;
}

// =============================================================================
// Artifacts API
// =============================================================================

export async function fetchArtifacts(sessionId: string): Promise<Artifact[]> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/artifacts`);

  if (!res.ok) {
    throw new Error(`Failed to fetch artifacts: ${res.status}`);
  }

  const data = await res.json();
  // Backend returns a direct array, not wrapped in an object
  return data.map((a: ApiArtifactResponse) => ({
    id: a.id,
    session_id: a.session_id,
    type: a.type,
    name: a.name,
    path: a.path,
    preview_url: a.preview_url,
    created_at: new Date(a.created_at),
    updated_at: new Date(a.updated_at),
  }));
}

// =============================================================================
// Webapp API
// =============================================================================

export async function fetchWebappInfo(
  sessionId: string
): Promise<ApiWebappInfoResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/webapp-info`);

  if (!res.ok) {
    throw new Error(`Failed to fetch webapp info: ${res.status}`);
  }

  return res.json();
}

// =============================================================================
// Files API
// =============================================================================

export async function fetchDirectoryListing(
  sessionId: string,
  path: string = ""
): Promise<DirectoryListing> {
  const url = new URL(
    `${API_BASE}/sessions/${sessionId}/files`,
    window.location.origin
  );
  if (path) {
    url.searchParams.set("path", path);
  }

  const res = await fetch(url.toString());

  if (!res.ok) {
    throw new Error(`Failed to fetch directory listing: ${res.status}`);
  }

  return res.json();
}

export interface FileContentResponse {
  content: string; // For text files: text content. For images: data URL (base64-encoded)
  mimeType: string;
  isImage?: boolean; // True if the content is an image data URL
  error?: string; // Error message if file can't be previewed
}

// Maximum file size for image preview (10MB)
const MAX_IMAGE_SIZE = 10 * 1024 * 1024;

/**
 * Fetch file content from the sandbox for preview.
 * Reuses the artifacts download endpoint but reads content as text.
 */
export async function fetchFileContent(
  sessionId: string,
  path: string
): Promise<FileContentResponse> {
  // Encode each path segment individually (spaces, special chars) but preserve slashes
  const encodedPath = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");

  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/artifacts/${encodedPath}`
  );

  if (!res.ok) {
    throw new Error(`Failed to fetch file content: ${res.status}`);
  }

  const mimeType = res.headers.get("Content-Type") || "text/plain";

  // For images, convert to data URL instead of blob URL (no cleanup needed)
  if (mimeType.startsWith("image/")) {
    const blob = await res.blob();

    // Check file size limit for images
    if (blob.size > MAX_IMAGE_SIZE) {
      return {
        content: "",
        mimeType,
        isImage: false,
        error: `Image too large to preview (${(
          blob.size /
          (1024 * 1024)
        ).toFixed(1)}MB). Maximum size is ${MAX_IMAGE_SIZE / (1024 * 1024)}MB.`,
      };
    }

    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        // Verify result is a string
        if (typeof reader.result !== "string") {
          reject(new Error("FileReader returned unexpected type"));
          return;
        }
        resolve({
          content: reader.result,
          mimeType,
          isImage: true,
        });
      };
      reader.onerror = () => {
        reject(new Error(reader.error?.message || "Failed to read image file"));
      };
      reader.readAsDataURL(blob);
    });
  }

  const content = await res.text();
  return { content, mimeType, isImage: false };
}

// =============================================================================
// Usage Limits API
// =============================================================================

/** Transform API response to frontend types */
function transformUsageLimitsResponse(
  data: ApiUsageLimitsResponse
): UsageLimits {
  return {
    isLimited: data.is_limited,
    limitType: data.limit_type,
    messagesUsed: data.messages_used,
    limit: data.limit,
    resetTimestamp: data.reset_timestamp
      ? new Date(data.reset_timestamp)
      : null,
  };
}

export async function fetchUsageLimits(): Promise<UsageLimits> {
  const res = await fetch(USAGE_LIMITS_ENDPOINT);

  if (!res.ok) {
    throw new Error(`Failed to fetch usage limits: ${res.status}`);
  }

  const data: ApiUsageLimitsResponse = await res.json();
  return transformUsageLimitsResponse(data);
}

// =============================================================================
// File Upload API
// =============================================================================

export interface UploadFileResponse {
  filename: string;
  path: string;
  size_bytes: number;
}

/**
 * Upload a file to the session's sandbox.
 * The file will be placed in the sandbox's user_uploaded_files directory.
 */
export async function uploadFile(
  sessionId: string,
  file: File
): Promise<UploadFileResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/sessions/${sessionId}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to upload file: ${res.status}`);
  }

  return res.json();
}

/**
 * Delete a file from the session's sandbox.
 */
export async function deleteFile(
  sessionId: string,
  path: string
): Promise<void> {
  // Encode each path segment individually (spaces, special chars) but preserve slashes
  const encodedPath = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");

  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/files/${encodedPath}`,
    {
      method: "DELETE",
    }
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to delete file: ${res.status}`);
  }
}

/**
 * Export a markdown file as DOCX.
 * Returns a Blob of the converted document.
 */
export async function exportDocx(
  sessionId: string,
  path: string
): Promise<Blob> {
  const encodedPath = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");

  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/export-docx/${encodedPath}`
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to export as DOCX: ${res.status}`
    );
  }

  return res.blob();
}

// =============================================================================
// PPTX Preview API
// =============================================================================

export interface PptxPreviewResponse {
  slide_count: number;
  slide_paths: string[];
  cached: boolean;
}

/**
 * Fetch PPTX slide preview images.
 * Triggers on-demand conversion (soffice → pdftoppm) with disk caching.
 */
export async function fetchPptxPreview(
  sessionId: string,
  path: string
): Promise<PptxPreviewResponse> {
  const encodedPath = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");

  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/pptx-preview/${encodedPath}`
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to generate PPTX preview: ${res.status}`
    );
  }

  return res.json();
}

// =============================================================================
// Connector Management API
// =============================================================================

export async function deleteConnector(
  connectorId: number,
  credentialId: number
): Promise<void> {
  const res = await fetch("/api/manage/admin/deletion-attempt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      connector_id: connectorId,
      credential_id: credentialId,
    }),
  });

  if (!res.ok) {
    const errorData = await res.json();
    throw new Error(
      errorData.detail || `Failed to delete connector: ${res.status}`
    );
  }
}

// =============================================================================
// User Library API
// =============================================================================

import {
  LibraryEntry,
  CreateDirectoryRequest,
  UploadResponse,
} from "@/app/craft/types/user-library";

const USER_LIBRARY_BASE = `${API_BASE}/user-library`;

/**
 * Fetch the user's library tree (uploaded files).
 */
export async function fetchLibraryTree(): Promise<LibraryEntry[]> {
  const res = await fetch(`${USER_LIBRARY_BASE}/tree`);

  if (!res.ok) {
    throw new Error(`Failed to fetch library tree: ${res.status}`);
  }

  return res.json();
}

/**
 * Upload files to the user library.
 */
export async function uploadLibraryFiles(
  path: string,
  files: File[]
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("path", path);
  for (const file of files) {
    formData.append("files", file);
  }

  const res = await fetch(`${USER_LIBRARY_BASE}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to upload files: ${res.status}`
    );
  }

  return res.json();
}

/**
 * Upload and extract a zip file to the user library.
 */
export async function uploadLibraryZip(
  path: string,
  file: File
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("path", path);
  formData.append("file", file);

  const res = await fetch(`${USER_LIBRARY_BASE}/upload-zip`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to upload zip: ${res.status}`);
  }

  return res.json();
}

/**
 * Create a directory in the user library.
 */
export async function createLibraryDirectory(
  request: CreateDirectoryRequest
): Promise<LibraryEntry> {
  const res = await fetch(`${USER_LIBRARY_BASE}/directories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to create directory: ${res.status}`
    );
  }

  return res.json();
}

/**
 * Toggle sync status for a file/directory in the user library.
 */
export async function toggleLibraryFileSync(
  documentId: string,
  enabled: boolean
): Promise<void> {
  const res = await fetch(
    `${USER_LIBRARY_BASE}/files/${encodeURIComponent(
      documentId
    )}/toggle?enabled=${enabled}`,
    {
      method: "PATCH",
    }
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to toggle sync: ${res.status}`);
  }
}

/**
 * Delete a file/directory from the user library.
 */
export async function deleteLibraryFile(documentId: string): Promise<void> {
  const res = await fetch(
    `${USER_LIBRARY_BASE}/files/${encodeURIComponent(documentId)}`,
    {
      method: "DELETE",
    }
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to delete file: ${res.status}`);
  }
}
