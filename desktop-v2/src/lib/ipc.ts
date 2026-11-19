// Typed wrappers for the Rust commands. Local windows never call the server directly.
import { Channel, invoke } from "@tauri-apps/api/core";

export interface ServerInfo {
  url: string;
  backendVersion: string;
}

export interface Prefs {
  serverUrl: string | null;
  hotkey: string;
  signedIn: boolean;
  // Why the launcher shortcut may not work, or null.
  shortcutNotice: string | null;
  launchAtLogin: boolean;
  // Settings that managed policy (MDM or Group Policy) sets.
  serverManaged: boolean;
  serverLocked: boolean;
  hotkeyManaged: boolean;
  launcherDisabled: boolean;
  launchAtLoginManaged: boolean;
  autoUpdateDisabled: boolean;
  notificationsDisabled: boolean;
  // A managed policy exists but is not valid.
  policyInvalid: boolean;
  notifyAnswers: boolean;
}

export interface SearchHit {
  documentId: string;
  title: string;
  link: string | null;
  blurb: string;
  sourceType: string;
}

export interface Citation {
  // The number the answer text uses, e.g. 3 for "[3]".
  number: number;
  title: string;
  link: string | null;
}

export type AskEvent =
  | { kind: "session"; chatSessionId: string }
  | { kind: "delta"; text: string }
  // What the answer is doing while no text streams.
  | { kind: "status"; text: string }
  // The text so far was narration before a tool step; the answer restarts.
  | { kind: "restart"; text: string }
  | { kind: "citations"; docs: Citation[] }
  | { kind: "needsApproval"; tool: string | null }
  | { kind: "done" }
  | { kind: "error"; message: string };

export const checkServer = (url: string): Promise<ServerInfo> =>
  invoke("check_server", { url });

export const saveServer = (url: string): Promise<void> =>
  invoke("save_server", { url });

export interface SsoOption {
  label: string;
  // Sign-in in the system browser; otherwise the server's login page in an
  // app window.
  browser: boolean;
  // The provider row the button starts; null for the legacy Google sign-in.
  provider: string | null;
}

export interface AuthMethods {
  password: boolean;
  sso: SsoOption[];
}

export const getAuthMethods = (): Promise<AuthMethods> => invoke("get_auth_methods");

/** "browser": continue in the system browser; "window": the in-app fallback opened. */
export const signInWithSso = (
  browser: boolean,
  provider: string | null = null
): Promise<"browser" | "window"> => invoke("sign_in_with_sso", { browser, provider });

export const login = (email: string, password: string): Promise<void> =>
  invoke("login", { email, password });

export const getPrefs = (): Promise<Prefs> => invoke("get_prefs");

export const setHotkey = (hotkey: string): Promise<void> =>
  invoke("set_hotkey", { hotkey });

export const setLaunchAtLogin = (enabled: boolean): Promise<void> =>
  invoke("set_launch_at_login", { enabled });
export const setNotifyAnswers = (enabled: boolean): Promise<void> =>
  invoke("set_notify_answers", { enabled });

export const changeServer = (): Promise<void> => invoke("change_server");

export const signOut = (): Promise<void> => invoke("sign_out");

// The server's built-in default agent.
export const DEFAULT_AGENT_ID = 0;

export interface Agent {
  id: number;
  name: string;
  description: string;
}

export interface LauncherAgents {
  agents: Agent[];
  // The saved agent for this server; null is the default agent.
  selected: number | null;
  // "Always Start with an Agent": the list has no default agent, so a new
  // chat needs one of the listed agents.
  defaultAgentDisabled: boolean;
}

export const listAgents = (): Promise<LauncherAgents> => invoke("list_agents");

export const setLauncherAgent = (agentId: number | null): Promise<void> =>
  invoke("set_launcher_agent", { agentId });

// A file uploaded and processed by the server, ready to send with a question.
export interface AttachedFile {
  userFileId: string;
  fileId: string;
  name: string;
  chatFileType: string;
}

/** The largest file the launcher can attach, in bytes. */
export const getUploadLimit = (): Promise<number> => invoke("get_upload_limit");

/**
 * Uploads the file and resolves once the server has processed it. `uploadId`
 * is the id that `cancelUpload` takes. Check `file.size` first: this reads
 * the whole file into memory.
 */
export async function uploadFile(
  file: File,
  name: string,
  uploadId: number
): Promise<AttachedFile> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  return invoke("upload_file", bytes, {
    headers: {
      "Onyx-File-Name": encodeURIComponent(name),
      "Onyx-File-Type": encodeURIComponent(file.type),
      "Onyx-Upload-Id": String(uploadId),
    },
  });
}

/** Stops an upload in flight; the app deletes the file if the server has it. */
export const cancelUpload = (uploadId: number): Promise<void> =>
  invoke("cancel_upload", { uploadId });

/** Deletes an uploaded file that was not sent. */
export const deleteUserFile = (userFileId: string): Promise<void> =>
  invoke("delete_user_file", { userFileId });

export interface AskOptions {
  // Continues that chat with a follow-up; null starts a new one.
  chatSessionId: string | null;
  // The agent of a new chat; null is the default agent.
  agentId: number | null;
  files: AttachedFile[];
}

export function ask(
  question: string,
  options: AskOptions,
  onEvent: (event: AskEvent) => void
): Promise<void> {
  const channel = new Channel<AskEvent>();
  channel.onmessage = onEvent;
  return invoke("ask", { question, ...options, onEvent: channel });
}

/** `sources` limits the search to these source types; empty searches all. */
export const search = (query: string, sources: string[] = []): Promise<SearchHit[]> =>
  invoke("search", { query, sources });

export const openChatInMain = (chatSessionId: string | null): Promise<void> =>
  invoke("open_chat_in_main", { chatSessionId });

export const openExternal = (url: string): Promise<void> =>
  invoke("open_external", { url });

export const hideLauncher = (): Promise<void> => invoke("hide_launcher");

// Tells Rust the launcher dropped its answer, so that answer does not notify.
export const discardAnswer = (): Promise<void> => invoke("discard_answer");

// Why the server could not be reached (reachability.rs).
export type Unreachable =
  | { kind: "noNetwork" }
  | { kind: "dns" }
  | { kind: "tls" }
  | { kind: "timeout" }
  | { kind: "refused" }
  | { kind: "serverError"; status: number }
  | { kind: "unknown" };

export interface OfflineStatus {
  host: string;
  reason: Unreachable;
  checking: boolean;
  // Milliseconds until the next automatic check.
  nextRetryMs: number | null;
  // Managed policy locks the server, so Change server is hidden.
  serverLocked: boolean;
}

export const OFFLINE_STATUS_EVENT = "offline-status";

export const getOfflineStatus = (): Promise<OfflineStatus | null> =>
  invoke("get_offline_status");

export const retryConnection = (): Promise<void> => invoke("retry_connection");

export function errorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
