import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import { parseErrorDetail } from "@/lib/fetcher";
import type { ScheduledRunContextResponse } from "@/app/craft/v1/tasks/types";
import { downloadFile } from "@/lib/download";
import { FetchError } from "@/lib/fetcher";
import {
  ApiSessionResponse,
  ApiDetailedSessionResponse,
  ApiMessageResponse,
  ApiInteractiveTurnResponse,
  ApiArtifactResponse,
  ApiWebappInfoResponse,
  ApiSandboxStatusResponse,
  SessionHistoryItem,
  Artifact,
  BuildMessageAttachment,
  BuildMessage,
  StreamPacket,
  DirectoryListing,
  SharingScope,
  ApiSessionSkillsState,
  type OutputInventory,
  type OutputCard,
} from "@/app/craft/types/streamingTypes";
import {
  ApprovalListResponse,
  ApprovalSubmitDecision,
  ApprovalView,
} from "@/app/craft/types/approvals";
import {
  RATE_LIMITED_ERROR_CODE,
  RateLimitDetails,
} from "@/app/app/interfaces";
import { BUILD_API_BASE } from "@/app/craft/v1/constants";
import type { ErrorResponseBody } from "@/lib/fetcher";
import { CRAFT_GATEWAY_PROVIDER } from "@/app/craft/onboarding/constants";
import type { BuildLlmSelection } from "@/app/craft/onboarding/constants";

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
            const data: StreamPacket = JSON.parse(dataStr);
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
}

// Pull the backend's human-readable error detail out of a failed response,
// falling back to the status code when the body isn't the expected shape.
async function errorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body: ErrorResponseBody | null = await res.json();
    if (typeof body?.detail === "string" && body.detail.trim()) {
      return body.detail;
    }
  } catch {
    // body wasn't JSON — fall through
  }
  return `${fallback}: ${res.status}`;
}

// Mirrors backend `SessionListResponse`.
interface ApiSessionListResponse {
  sessions: ApiSessionResponse[];
}

export async function createSession(
  options?: CreateSessionOptions
): Promise<ApiDetailedSessionResponse> {
  const res = await fetch(`${BUILD_API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: options?.name || null,
    }),
  });

  if (!res.ok) {
    throw new Error(await errorDetail(res, "Failed to create session"));
  }

  return res.json();
}

export async function fetchSession(
  sessionId: string,
  options?: { checkWorkspace?: boolean }
): Promise<ApiDetailedSessionResponse> {
  const params = new URLSearchParams();
  if (options?.checkWorkspace === false) {
    params.set("check_workspace", "false");
  }
  const query = params.size > 0 ? `?${params}` : "";
  const res = await fetch(`${BUILD_API_BASE}/sessions/${sessionId}${query}`);

  if (!res.ok) {
    throw new Error(`Failed to load session: ${res.status}`);
  }

  return res.json();
}

export async function reloadSessionSkills(
  sessionId: string
): Promise<ApiSessionSkillsState> {
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/skills/reload`,
    { method: "POST" }
  );

  if (!res.ok) {
    throw new Error(await errorDetail(res, "Failed to reload session"));
  }

  return res.json();
}

export async function fetchSandboxStatus(
  sessionId: string
): Promise<ApiSandboxStatusResponse> {
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/sandbox-status`
  );

  if (!res.ok) {
    throw new Error(`Failed to fetch sandbox status: ${res.status}`);
  }

  return res.json();
}

export async function fetchSessionHistory(): Promise<SessionHistoryItem[]> {
  const res = await fetch(`${BUILD_API_BASE}/sessions`);

  if (!res.ok) {
    throw new Error(`Failed to fetch session history: ${res.status}`);
  }

  const data: ApiSessionListResponse = await res.json();
  return data.sessions.map((s: ApiSessionResponse) => ({
    id: s.id,
    title: s.name || `Session ${s.id.slice(0, 8)}...`,
    createdAt: new Date(s.created_at),
  }));
}

export async function updateSessionName(
  sessionId: string,
  name: string | null
): Promise<ApiSessionResponse> {
  const res = await fetch(`${BUILD_API_BASE}/sessions/${sessionId}/name`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });

  if (!res.ok) {
    throw new Error(`Failed to update session name: ${res.status}`);
  }

  return res.json();
}

export async function setSessionSharing(
  sessionId: string,
  sharingScope: SharingScope
): Promise<{ session_id: string; sharing_scope: SharingScope }> {
  const res = await fetch(`${BUILD_API_BASE}/sessions/${sessionId}/public`, {
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
  const res = await fetch(`${BUILD_API_BASE}/sessions/${sessionId}`, {
    method: "DELETE",
  });

  if (!res.ok) {
    throw new Error(`Failed to delete session: ${res.status}`);
  }
}

// ~2 min of retries — covers a concurrent provision + snapshot restore; the
// backend's per-sandbox lock itself expires at 300s.
const RESTORE_CONFLICT_RETRY_DELAY_MS = 2000;
const RESTORE_CONFLICT_MAX_RETRIES = 60;

export async function restoreSession(
  sessionId: string,
  // Overridable for tests; production callers use the module defaults.
  opts: { retryDelayMs?: number; maxRetries?: number } = {}
): Promise<ApiDetailedSessionResponse> {
  const retryDelayMs = opts.retryDelayMs ?? RESTORE_CONFLICT_RETRY_DELAY_MS;
  const maxRetries = opts.maxRetries ?? RESTORE_CONFLICT_MAX_RETRIES;

  for (let attempt = 0; ; attempt++) {
    const res = await fetch(`${BUILD_API_BASE}/sessions/${sessionId}/restore`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    if (res.ok) {
      return res.json();
    }

    // 409 = another tab/request holds the restore lock; it's transient, so
    // retry until that restore finishes rather than surfacing it as a failure.
    if (res.status === 409 && attempt < maxRetries) {
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      continue;
    }

    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to restore session: ${res.status}`
    );
  }
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
    `${BUILD_API_BASE}/sessions/${sessionId}/pre-provisioned-check`
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

function extractAttachmentsFromMetadata(
  metadata: Record<string, any> | null | undefined
): BuildMessageAttachment[] {
  if (!Array.isArray(metadata?.attachments)) return [];

  // Element of an unvalidated attachments array; the body below decodes it.
  // oxlint-disable-next-line anti-slop/no-unknown-parameters
  return metadata.attachments.flatMap((attachment: unknown) => {
    if (
      typeof attachment !== "object" ||
      attachment === null ||
      !("name" in attachment) ||
      !("path" in attachment) ||
      !("mime_type" in attachment) ||
      typeof attachment.name !== "string" ||
      typeof attachment.path !== "string" ||
      typeof attachment.mime_type !== "string"
    ) {
      return [];
    }

    return [
      {
        name: attachment.name,
        path: attachment.path,
        mimeType: attachment.mime_type,
      },
    ];
  });
}

// Mirrors backend `MessageListResponse`.
interface ApiMessageListResponse {
  messages: ApiMessageResponse[];
}

export async function fetchMessages(
  sessionId: string
): Promise<BuildMessage[]> {
  const res = await fetch(`${BUILD_API_BASE}/sessions/${sessionId}/messages`);

  if (!res.ok) {
    throw new Error(`Failed to fetch messages: ${res.status}`);
  }

  const data: ApiMessageListResponse = await res.json();
  return data.messages.map((m: ApiMessageResponse) => ({
    id: m.id,
    type: m.type,
    turn_index: m.turn_index,
    // Content is stored in message_metadata, not as a separate field
    content: m.content || extractContentFromMetadata(m.message_metadata),
    attachments: extractAttachmentsFromMetadata(m.message_metadata),
    message_metadata: m.message_metadata,
    timestamp: new Date(m.created_at),
  }));
}

// 429 JSON body emitted by the backend usage rate-limiter (token/cost budgets).
interface RateLimited429Body {
  error_code?: string;
  detail?: string;
  scope?: string;
  reset_at?: string;
  retry_after_seconds?: number;
}

/**
 * Thrown when the backend's usage rate-limiter (org/user token + cost
 * budgets) rejects a turn with a structured 429. Carries the reset details
 * so the UI can render the same rate-limit banner as chat.
 */
export class RateLimitedError extends Error {
  public readonly details: RateLimitDetails;

  constructor(message: string, details: RateLimitDetails) {
    super(message);
    this.name = "RateLimitedError";
    this.details = details;
  }
}

export async function createTurn(
  sessionId: string,
  content: string,
  clientRequestId: string,
  signal?: AbortSignal,
  model?: BuildLlmSelection | null,
  attachments: BuildMessageAttachment[] = []
): Promise<ApiInteractiveTurnResponse> {
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/send-message`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content,
        client_request_id: clientRequestId,
        attachments: attachments.map((attachment) => ({
          name: attachment.name,
          path: attachment.path,
          mime_type: attachment.mimeType,
        })),
        provider: model ? CRAFT_GATEWAY_PROVIDER : undefined,
        provider_id: model?.providerId,
        model: model?.modelName,
      }),
      signal,
    }
  );

  if (!res.ok) {
    if (res.status === 429) {
      const body: RateLimited429Body | null = await res
        .json()
        .catch(() => null);
      if (body?.error_code === RATE_LIMITED_ERROR_CODE) {
        throw new RateLimitedError(
          body.detail || "You've reached your usage limit.",
          {
            scope: body.scope,
            reset_at: body.reset_at,
            retry_after_seconds: body.retry_after_seconds,
          }
        );
      }
      throw new Error(body?.detail || `Failed to create turn: ${res.status}`);
    }
    throw new Error(await errorDetail(res, "Failed to create turn"));
  }

  return res.json();
}

export async function fetchActiveTurn(
  sessionId: string
): Promise<ApiInteractiveTurnResponse | null> {
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/turns/active`
  );

  if (!res.ok) {
    throw new FetchError(
      `Failed to fetch active turn: ${res.status}`,
      res.status,
      null
    );
  }

  return await res.json();
}

export async function fetchKnownTurn(
  sessionId: string,
  turnId: string
): Promise<ApiInteractiveTurnResponse | null> {
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/turns/${turnId}`
  );
  if (!res.ok) {
    throw new FetchError(
      `Failed to fetch turn: ${res.status}`,
      res.status,
      null
    );
  }
  return res.json();
}

export async function fetchTurnEventStream(
  sessionId: string,
  turnId: string,
  signal?: AbortSignal
): Promise<Response | null> {
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/turns/${turnId}/events`,
    { headers: { Accept: "text/event-stream" }, signal }
  );

  if (!res.ok) {
    if (res.status === 404 || res.status === 409) {
      return null;
    }
    throw new FetchError(
      `Failed to stream turn: ${res.status}`,
      res.status,
      null
    );
  }

  return res;
}

/**
 * Interrupt the in-flight agent turn for a session. The backend interrupts the
 * sandbox turn; any attached live stream then terminates normally.
 */
export async function interruptMessageStream(
  sessionId: string,
  turnId?: string
): Promise<boolean> {
  const query = turnId ? `?turn_id=${encodeURIComponent(turnId)}` : "";
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/interrupt${query}`,
    {
      method: "POST",
    }
  );

  if (!res.ok) {
    throw new Error(`Failed to interrupt message: ${res.status}`);
  }
  const result: { interrupted: boolean } = await res.json();
  return result.interrupted;
}

export async function fetchScheduledRunContext(
  sessionId: string
): Promise<ScheduledRunContextResponse> {
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/scheduled-run-context`
  );
  if (!res.ok)
    throw new FetchError(
      await errorDetail(res, "Failed to fetch scheduled run"),
      res.status,
      null
    );
  return res.json();
}

export async function fetchScheduledRunEventStream(
  sessionId: string,
  signal?: AbortSignal
): Promise<Response> {
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/scheduled-run-events`,
    { headers: { Accept: "text/event-stream" }, signal }
  );

  if (res.status === 409) {
    return new Response("");
  }

  if (!res.ok) {
    throw new FetchError(
      `Failed to stream scheduled run: ${res.status}`,
      res.status,
      null
    );
  }

  return res;
}

// =============================================================================
// Artifacts API
// =============================================================================

export async function fetchArtifacts(sessionId: string): Promise<Artifact[]> {
  const res = await fetch(`${BUILD_API_BASE}/sessions/${sessionId}/artifacts`);

  if (!res.ok) {
    throw new Error(`Failed to fetch artifacts: ${res.status}`);
  }

  const data: ApiArtifactResponse[] = await res.json();
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

export async function fetchOutputCards(
  sessionId: string
): Promise<OutputCard[]> {
  const response = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/output-cards`
  );
  if (!response.ok)
    throw new FetchError(
      `Failed to fetch output cards: ${response.status}`,
      response.status,
      null
    );
  const result: { cards: OutputCard[] } = await response.json();
  return result.cards;
}

export async function markOutputsViewed(
  sessionId: string,
  cards: readonly OutputCard[]
): Promise<OutputCard[]> {
  const response = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/output-cards/viewed`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        revisions: Object.fromEntries(
          cards.map((card) => [card.id, card.revision])
        ),
      }),
    }
  );
  if (!response.ok)
    throw new FetchError(
      `Failed to mark outputs viewed: ${response.status}`,
      response.status,
      null
    );
  const result: { cards: OutputCard[] } = await response.json();
  return result.cards;
}

export async function markOutputViewed(
  sessionId: string,
  card: OutputCard
): Promise<OutputCard> {
  const response = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/output-cards/${card.id}/viewed`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision: card.revision }),
    }
  );
  if (!response.ok)
    throw new FetchError(
      `Failed to mark output viewed: ${response.status}`,
      response.status,
      null
    );
  return response.json();
}

export async function fetchWebappInfo(
  sessionId: string,
  signal?: AbortSignal
): Promise<ApiWebappInfoResponse> {
  const res = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/webapp-info`,
    { signal }
  );

  if (!res.ok) {
    throw new FetchError(
      `Failed to fetch webapp info: ${res.status}`,
      res.status,
      null
    );
  }

  return res.json();
}

// =============================================================================
// Files API
// =============================================================================

export async function fetchOutputInventory(
  sessionId: string,
  signal?: AbortSignal
): Promise<OutputInventory> {
  const response = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/outputs`,
    { signal }
  );
  if (!response.ok)
    throw new FetchError(
      `Failed to fetch output inventory: ${response.status}`,
      response.status,
      null
    );
  return response.json();
}

export async function fetchDirectoryListing(
  sessionId: string,
  path: string = "",
  signal?: AbortSignal
): Promise<DirectoryListing> {
  const url = new URL(
    `${BUILD_API_BASE}/sessions/${sessionId}/files`,
    window.location.origin
  );
  if (path) {
    url.searchParams.set("path", path);
  }

  const controller = new AbortController();
  const timeout = setTimeout(
    () =>
      controller.abort(
        new DOMException("Directory listing timed out", "TimeoutError")
      ),
    10_000
  );
  try {
    const res = await fetch(url.toString(), {
      signal: signal
        ? AbortSignal.any([signal, controller.signal])
        : controller.signal,
    });
    if (!res.ok) {
      throw new FetchError(
        `Failed to fetch directory listing: ${res.status}`,
        res.status,
        null
      );
    }
    return await res.json();
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Build an encoded sandbox file URL for previews and downloads.
 */
export function buildArtifactUrl(sessionId: string, path: string): string {
  const encodedPath = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return `${BUILD_API_BASE}/sessions/${sessionId}/artifacts/${encodedPath}`;
}

export function downloadArtifactFile(sessionId: string, path: string): void {
  downloadFile(path.split("/").pop() || path, {
    url: buildArtifactUrl(sessionId, path),
  });
}

/**
 * Trigger a browser download for a directory as a zip file.
 */
export function downloadDirectory(sessionId: string, path: string): void {
  const encodedPath = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  downloadFile("", {
    url: `${BUILD_API_BASE}/sessions/${sessionId}/download-directory/${encodedPath}`,
  });
}

export interface FileContentResponse {
  content: string; // For text files: text content. For images: data URL (base64-encoded)
  mimeType: string;
  isImage?: boolean; // True if the content is an image data URL
  error?: "unsupported_binary" | "image_too_large";
}

// Maximum file size for image preview (10MB)
const MAX_IMAGE_SIZE = 10 * 1024 * 1024;
const MAX_UNKNOWN_TEXT_SIZE = 10 * 1024 * 1024;

/**
 * Fetch file content from the sandbox for preview.
 * Reuses the artifacts download endpoint but reads content as text.
 */
function imageBlobDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("FileReader returned unexpected type"));
    };
    reader.onerror = () =>
      reject(new Error(reader.error?.message || "Failed to read image file"));
    reader.readAsDataURL(blob);
  });
}

/** Fetch the sandbox converter's cached first page without mounting a document viewer. */
export async function fetchOutputThumbnail(
  sessionId: string,
  path: string
): Promise<string> {
  const encodedPath = path.split("/").map(encodeURIComponent).join("/");
  const response = await fetch(
    `${BUILD_API_BASE}/sessions/${sessionId}/output-thumbnail/${encodedPath}`,
    { cache: "no-store" }
  );
  if (!response.ok)
    throw new FetchError(
      `Failed to fetch thumbnail: ${response.status}`,
      response.status,
      null
    );
  return imageBlobDataUrl(await response.blob());
}

export async function fetchFileContent(
  sessionId: string,
  path: string
): Promise<FileContentResponse> {
  const res = await fetch(buildArtifactUrl(sessionId, path), {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new FetchError(
      `Failed to fetch file content: ${res.status}`,
      res.status,
      null
    );
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
        error: "image_too_large",
      };
    }

    return { content: await imageBlobDataUrl(blob), mimeType, isImage: true };
  }

  const textMimeType =
    /^(text\/|application\/(json|(?:[^;]+\+)?json|xml|(?:[^;]+\+)?xml|javascript|x-yaml|yaml))/i.test(
      mimeType
    );
  // MIME guessing often labels source files as binary (for example TSX and TypeScript).
  const sourceFile =
    /\.(?:py|js|jsx|ts|tsx|mjs|cjs|sql|sh|bash|zsh|css|scss|sass|html?|xml|ya?ml|toml|ini|conf|config|env|log|go|rs|java|c|cpp|h|hpp|rb|r|vue|svelte|md|txt|csv)$/i.test(
      path
    ) || /(?:^|\/)(?:Dockerfile|Makefile|README|LICENSE)$/i.test(path);
  if (!textMimeType && !sourceFile) {
    if (/^application\/octet-stream(?:;|$)/i.test(mimeType)) {
      const bytes = await res.arrayBuffer();
      if (
        bytes.byteLength <= MAX_UNKNOWN_TEXT_SIZE &&
        !new Uint8Array(bytes).some(
          (byte) => byte < 9 || (byte >= 14 && byte < 32)
        )
      ) {
        try {
          const content = new TextDecoder("utf-8", { fatal: true }).decode(
            bytes
          );
          return { content, mimeType, isImage: false };
        } catch {
          // Unknown binary files must not become replacement-character text previews.
        }
      }
    }

    return {
      content: "",
      mimeType,
      isImage: false,
      error: "unsupported_binary",
    };
  }

  const content = await res.text();
  return { content, mimeType, isImage: false };
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

  const res = await fetch(`${BUILD_API_BASE}/sessions/${sessionId}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
    throw new FetchError(
      errorData.detail || `Failed to upload file: ${res.status}`,
      res.status,
      errorData
    );
  }

  return res.json();
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
    `${BUILD_API_BASE}/sessions/${sessionId}/export-docx/${encodedPath}`
  );

  if (!res.ok) {
    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
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
    `${BUILD_API_BASE}/sessions/${sessionId}/pptx-preview/${encodedPath}`,
    { cache: "no-store" }
  );

  if (!res.ok) {
    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
    throw new FetchError(
      errorData.detail || `Failed to generate PPTX preview: ${res.status}`,
      res.status,
      errorData
    );
  }

  return res.json();
}

// =============================================================================
// Approvals API
// =============================================================================

export async function fetchLiveApprovals(
  sessionId: string
): Promise<ApprovalListResponse> {
  const res = await fetch(
    `${BUILD_API_BASE}/approvals/sessions/${sessionId}/live`
  );

  if (!res.ok) {
    throw new Error(`Failed to fetch live approvals: ${res.status}`);
  }

  return res.json();
}

// Lets the approval card distinguish "already resolved" from a generic
// network error so both can flow through the same SWR revalidation
// while keeping logs clean.
export class ApprovalConflictError extends Error {
  public readonly statusCode: number = 409;

  constructor(detail: string) {
    super(detail);
    this.name = "ApprovalConflictError";
  }
}

export async function postApprovalDecision(
  approvalId: string,
  decision: ApprovalSubmitDecision
): Promise<ApprovalView> {
  const res = await fetch(
    `${BUILD_API_BASE}/approvals/${approvalId}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    }
  );

  if (res.status === 409) {
    const body: ErrorResponseBody = await res.json().catch(() => ({}));
    throw new ApprovalConflictError(body.detail ?? "decision conflict");
  }
  if (!res.ok) {
    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to post approval decision: ${res.status}`
    );
  }
  return res.json();
}

export async function postApprovalSessionGrant(
  approvalId: string
): Promise<ApprovalView> {
  const res = await fetch(
    `${BUILD_API_BASE}/approvals/${approvalId}/session-grant`,
    {
      method: "POST",
    }
  );

  if (res.status === 409) {
    const body: ErrorResponseBody = await res.json().catch(() => ({}));
    throw new ApprovalConflictError(body.detail ?? "decision conflict");
  }
  if (!res.ok) {
    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to approve for session: ${res.status}`
    );
  }
  return res.json();
}

// =============================================================================
// User Library API
// =============================================================================

import {
  LibraryEntry,
  CreateDirectoryRequest,
  UploadResponse,
} from "@/app/craft/types/user-library";

const USER_LIBRARY_BASE = `${BUILD_API_BASE}/user-library`;

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
    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
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
    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
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
    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to create directory: ${res.status}`
    );
  }

  return res.json();
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
    const errorData: ErrorResponseBody = await res.json().catch(() => ({}));
    throw new FetchError(
      errorData.detail || `Failed to delete file: ${res.status}`,
      res.status,
      errorData
    );
  }
}

export async function saveAppActionPolicies(
  scope: "personal" | "workspace",
  appId: number,
  actionPolicies: Record<string, ActionPolicy>,
  errorMessage: string,
  usersCanManagePolicies?: boolean
): Promise<void> {
  const admin = scope === "workspace";
  const response = await fetch(
    `/api/build/${admin ? "admin/" : ""}action-policies/${appId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        users_can_manage_policies: usersCanManagePolicies,
        action_policies: actionPolicies,
      }),
    }
  );
  if (!response.ok)
    throw new Error(await parseErrorDetail(response, errorMessage));
}
