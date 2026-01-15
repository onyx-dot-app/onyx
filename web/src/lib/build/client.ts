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

export type BuildEvent =
  | { type: "output"; data: OutputEvent }
  | { type: "status"; data: StatusEvent }
  | { type: "artifact"; data: ArtifactEvent }
  | { type: "error"; data: ErrorEvent };

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

export function getWebappUrl(path: string = ""): string {
  return `/api/build/webapp${path ? `/${path}` : ""}`;
}
