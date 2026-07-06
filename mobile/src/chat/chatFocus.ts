// Maps pathname → ChatSurface focus; null = non-chat route (surface hides). Pure for tests.
export type ChatFocus =
  | { kind: "new"; sessionId: null; projectId: null }
  | { kind: "chat"; sessionId: string; projectId: null }
  | { kind: "project"; sessionId: null; projectId: number };

const CHAT_PREFIX = "/chat/";
const PROJECT_PREFIX = "/projects/";

export function deriveFocus(pathname: string): ChatFocus | null {
  if (pathname === "/") {
    return { kind: "new", sessionId: null, projectId: null };
  }
  if (pathname.startsWith(CHAT_PREFIX)) {
    const id = firstSegment(pathname.slice(CHAT_PREFIX.length));
    return id ? { kind: "chat", sessionId: id, projectId: null } : null;
  }
  if (pathname.startsWith(PROJECT_PREFIX)) {
    const raw = firstSegment(pathname.slice(PROJECT_PREFIX.length));
    const projectId = Number(raw);
    // Number("") is a finite 0; require a non-empty id.
    return raw && Number.isFinite(projectId)
      ? { kind: "project", sessionId: null, projectId }
      : null;
  }
  return null;
}

function firstSegment(rest: string): string {
  const slash = rest.indexOf("/");
  return slash === -1 ? rest : rest.slice(0, slash);
}
