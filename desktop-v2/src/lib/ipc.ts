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
  // The built-in Google sign-in in the system browser; otherwise the server's
  // login page in an app window.
  browser: boolean;
}

export interface AuthMethods {
  password: boolean;
  sso: SsoOption[];
  browserSso: boolean;
}

export const getAuthMethods = (): Promise<AuthMethods> => invoke("get_auth_methods");

/** "browser": continue in the system browser; "window": the in-app fallback opened. */
export const signInWithSso = (browser: boolean): Promise<"browser" | "window"> =>
  invoke("sign_in_with_sso", { browser });

export const login = (email: string, password: string): Promise<void> =>
  invoke("login", { email, password });

export const getPrefs = (): Promise<Prefs> => invoke("get_prefs");

export const setHotkey = (hotkey: string): Promise<void> =>
  invoke("set_hotkey", { hotkey });

export const changeServer = (): Promise<void> => invoke("change_server");

export const signOut = (): Promise<void> => invoke("sign_out");

export function ask(
  question: string,
  onEvent: (event: AskEvent) => void
): Promise<void> {
  const channel = new Channel<AskEvent>();
  channel.onmessage = onEvent;
  return invoke("ask", { question, onEvent: channel });
}

export const search = (query: string): Promise<SearchHit[]> =>
  invoke("search", { query });

export const openChatInMain = (chatSessionId: string | null): Promise<void> =>
  invoke("open_chat_in_main", { chatSessionId });

export const openExternal = (url: string): Promise<void> =>
  invoke("open_external", { url });

export const hideLauncher = (): Promise<void> => invoke("hide_launcher");

export function errorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
