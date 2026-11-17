// Typed wrappers for the Rust commands. Local windows never call the server directly.
import { invoke } from "@tauri-apps/api/core";

export interface ServerInfo {
  url: string;
  backendVersion: string;
}

export interface Prefs {
  serverUrl: string | null;
  signedIn: boolean;
}

export const checkServer = (url: string): Promise<ServerInfo> =>
  invoke("check_server", { url });

export const saveServer = (url: string): Promise<void> =>
  invoke("save_server", { url });



export const login = (email: string, password: string): Promise<void> =>
  invoke("login", { email, password });

export const getPrefs = (): Promise<Prefs> => invoke("get_prefs");

export const changeServer = (): Promise<void> => invoke("change_server");

export const signOut = (): Promise<void> => invoke("sign_out");

export const openExternal = (url: string): Promise<void> =>
  invoke("open_external", { url });

export function errorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
