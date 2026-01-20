import {
  ApiSessionResponse,
  ApiMessageResponse,
  ApiArtifactResponse,
  ApiUsageLimitsResponse,
  SessionHistoryItem,
  Artifact,
  BuildMessage,
  StreamPacket,
  UsageLimits,
} from "@/app/build/services/buildStreamingModels";

// =============================================================================
// API Configuration
// =============================================================================

const API_BASE = "/api/build/v1";
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

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          onPacket(data);
        } catch {
          // Ignore parse errors
        }
      }
    }
  }
}

// =============================================================================
// Session API
// =============================================================================

export async function createSession(name: string): Promise<ApiSessionResponse> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });

  if (!res.ok) {
    throw new Error(`Failed to create session: ${res.status}`);
  }

  return res.json();
}

export async function fetchSession(
  sessionId: string
): Promise<ApiSessionResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: "PUT",
  });

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

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: "DELETE",
  });

  if (!res.ok) {
    throw new Error(`Failed to delete session: ${res.status}`);
  }
}

// =============================================================================
// Messages API
// =============================================================================

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
    role: m.role,
    content: m.content,
    timestamp: new Date(m.created_at),
  }));
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
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
    signal,
  });

  if (!res.ok) {
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
  return data.artifacts.map((a: ApiArtifactResponse) => ({
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
