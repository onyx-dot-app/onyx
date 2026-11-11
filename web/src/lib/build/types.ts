import type { FileSystemEntry } from "@/app/craft/types/streamingTypes";

export interface RegisteredWebapp {
  id: string;
  name: string;
  /** The authorized session proxy route, never the sandbox's raw address. */
  url: string;
  state: "starting" | "ready" | "unavailable";
}

export type AppDiscoveryState = "checking" | "ready" | "unavailable" | "failed";

export interface SearchInventory {
  entries: FileSystemEntry[];
  complete: boolean;
  failedDirectories: string[];
}

export interface FilePreviewResult<T> {
  identity: string;
  data?: T;
  error?: Error;
}
