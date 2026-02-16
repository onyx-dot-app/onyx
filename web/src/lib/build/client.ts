export interface CreateSessionRequest {
  task: string;
  available_sources?: string[];
}

export interface CreateSessionResponse {
  session_id: string;
}

export interface ArtifactInfo {
  artifact_type: "webapp" | "file" | "markdown" | "image";
  path: string;
  filename: string;
  mime_type?: string;
}

// =============================================================================
// ACP Event Types (from Agent Client Protocol)
// =============================================================================

/** Text or image content from the agent */
export interface AgentMessageChunkEvent {
  sessionUpdate: "agent_message_chunk";
  content: Array<{
    type: "text" | "image";
    text?: string;
    image?: string;
    mimeType?: string;
  }>;
}

/** Agent's internal reasoning/thinking */
export interface AgentThoughtChunkEvent {
  sessionUpdate: "agent_thought_chunk";
  thought: string;
}

/** Tool invocation started */
export interface ToolCallStartEvent {
  sessionUpdate: "tool_call";
  toolCallId: string;
  toolName: string;
  toolInput?: Record<string, unknown>;
}

/** Tool execution progress/result */
export interface ToolCallProgressEvent {
  sessionUpdate: "tool_call_update";
  toolCallId: string;
  content?: Array<{
    type: "text" | "image";
    text?: string;
    image?: string;
    mimeType?: string;
  }>;
  error?: string;
  isComplete?: boolean;
}

/** Agent's execution plan */
export interface AgentPlanUpdateEvent {
  sessionUpdate: "plan";
  plan: Array<{
    id: string;
    description: string;
    status: "pending" | "in_progress" | "completed" | "failed";
  }>;
}

/** Agent mode change */
export interface CurrentModeUpdateEvent {
  sessionUpdate: "current_mode_update";
  mode: string;
}

/** Agent finished processing prompt */
export interface PromptResponseEvent {
  stopReason?: string;
  usage?: {
    inputTokens?: number;
    outputTokens?: number;
  };
}

/** ACP error event */
export interface ACPErrorEvent {
  code: number;
  message: string;
}

/** File write event (custom Onyx extension) */
export interface FileWriteEvent {
  path: string;
  size_bytes?: number;
  operation?: "create" | "update" | "delete";
}

// =============================================================================
// Legacy Event Types (kept for backwards compatibility)
// =============================================================================

export interface OutputEvent {
  stream: "stdout" | "stderr";
  data: string;
}

export interface StatusEvent {
  status: "running" | "completed" | "failed";
  message?: string;
}

export interface ArtifactEvent {
  artifact_type: string;
  path: string;
  filename: string;
}

export interface ErrorEvent {
  message: string;
}

export interface FileSystemEntry {
  name: string;
  path: string;
  is_directory: boolean;
  size: number | null;
  mime_type: string | null;
}

export interface DirectoryListing {
  path: string;
  entries: FileSystemEntry[];
}

// =============================================================================
// Union Types
// =============================================================================

/** All possible ACP events from the agent */
export type ACPEvent =
  | { type: "agent_message_chunk"; data: AgentMessageChunkEvent }
  | { type: "agent_thought_chunk"; data: AgentThoughtChunkEvent }
  | { type: "tool_call"; data: ToolCallStartEvent }
  | { type: "tool_call_update"; data: ToolCallProgressEvent }
  | { type: "plan"; data: AgentPlanUpdateEvent }
  | { type: "current_mode_update"; data: CurrentModeUpdateEvent }
  | { type: "prompt_response"; data: PromptResponseEvent }
  | { type: "error"; data: ACPErrorEvent }
  | { type: "status"; data: StatusEvent }
  | { type: "artifact"; data: ArtifactEvent }
  | { type: "file_write"; data: FileWriteEvent };

/** Legacy BuildEvent type - alias for ACPEvent */
export type BuildEvent = ACPEvent;

export async function createSession(
  request: CreateSessionRequest
): Promise<CreateSessionResponse> {
  const response = await fetch("/api/build/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`Failed to create session: ${response.statusText}`);
  }
  return response.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(`/api/build/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Failed to delete session: ${response.statusText}`);
  }
}

export async function executeTask(
  sessionId: string,
  task: string,
  context: string | undefined,
  onEvent: (event: BuildEvent) => void,
  onError: (error: Error) => void,
  onComplete: () => void
): Promise<void> {
  try {
    const response = await fetch(`/api/build/sessions/${sessionId}/execute`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ task, context }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No response body");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      let currentEventType = "output";
      for (const line of lines) {
        if (line.startsWith("event:")) {
          currentEventType = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          const data = line.slice(5).trim();
          if (data) {
            try {
              const parsed = JSON.parse(data);
              onEvent({ type: currentEventType, data: parsed } as BuildEvent);
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }
    }

    onComplete();
  } catch (error) {
    onError(error instanceof Error ? error : new Error(String(error)));
  }
}

/**
 * Send a message to the build session using the new messages API endpoint.
 * This endpoint streams SSE events with message-prefixed packet types.
 */
export async function sendMessage(
  sessionId: string,
  message: string,
  onEvent: (event: BuildEvent) => void,
  onError: (error: Error) => void,
  onComplete: () => void
): Promise<void> {
  try {
    const response = await fetch(`/api/build/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ content: message }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        `HTTP ${response.status}: ${errorText || response.statusText}`
      );
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No response body");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("event:")) {
          // Skip event type line (all events are "message")
          continue;
        } else if (line.startsWith("data:")) {
          const data = line.slice(5).trim();
          if (data) {
            try {
              const parsed = JSON.parse(data);
              // Map frontend packet types to BuildEvent types
              const eventType = mapMessagePacketToEventType(parsed.type);
              if (eventType) {
                onEvent({ type: eventType, data: parsed } as BuildEvent);
              }
            } catch (err) {
              console.error("Failed to parse SSE data:", err);
            }
          }
        }
      }
    }

    onComplete();
  } catch (error) {
    onError(error instanceof Error ? error : new Error(String(error)));
  }
}

/**
 * Map message API packet types to BuildEvent types.
 * Uses direct ACP event names from the backend, plus custom Onyx packet types.
 */
function mapMessagePacketToEventType(packetType: string): string | null {
  const mapping: Record<string, string> = {
    // Direct ACP event types
    agent_message_chunk: "agent_message_chunk",
    agent_thought_chunk: "agent_thought_chunk",
    tool_call_start: "tool_call",
    tool_call_progress: "tool_call_update",
    agent_plan_update: "plan",
    current_mode_update: "current_mode_update",
    prompt_response: "prompt_response",
    error: "error",
    // Custom Onyx packet types (extensions to ACP)
    artifact_created: "artifact",
    file_write: "file_write",
  };
  return mapping[packetType] || null;
}

export async function listArtifacts(
  sessionId: string
): Promise<ArtifactInfo[]> {
  const response = await fetch(`/api/build/sessions/${sessionId}/artifacts`);
  if (!response.ok) {
    throw new Error(`Failed to list artifacts: ${response.statusText}`);
  }
  return response.json();
}

export function getArtifactUrl(sessionId: string, path: string): string {
  return `/api/build/sessions/${sessionId}/artifacts/${path}`;
}

export async function listDirectory(
  sessionId: string,
  path: string = ""
): Promise<DirectoryListing> {
  const url = path
    ? `/api/build/sessions/${sessionId}/files?path=${encodeURIComponent(path)}`
    : `/api/build/sessions/${sessionId}/files`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to list directory: ${response.statusText}`);
  }
  return response.json();
}

export function getWebappUrl(sessionId: string, path: string = ""): string {
  return `/api/build/sessions/${sessionId}/webapp${path ? `/${path}` : ""}`;
}
