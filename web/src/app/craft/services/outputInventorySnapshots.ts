import { normalizePanelPath } from "@/app/craft/types/displayTypes";
import type { OutputFile } from "@/app/craft/types/streamingTypes";

const MAX_CHARACTERS = 256_000;
const MAX_FILES = 2000;
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

function storageKey(userId: string, sessionId: string): string {
  return `onyx:craft:outputs:v1:${userId}:${sessionId}`;
}

/** Display hint only: stored files cannot establish the task's discovery baseline. */
export function readOutputInventorySnapshot(
  userId: string,
  sessionId: string
): Record<string, OutputFile> | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const raw = window.sessionStorage.getItem(storageKey(userId, sessionId));
    if (!raw || raw.length > MAX_CHARACTERS) return undefined;
    const value: unknown = JSON.parse(raw);
    if (
      typeof value !== "object" ||
      value === null ||
      !("readAt" in value) ||
      typeof value.readAt !== "number" ||
      !Number.isFinite(value.readAt) ||
      value.readAt > Date.now() ||
      Date.now() - value.readAt > MAX_AGE_MS ||
      !("files" in value) ||
      !Array.isArray(value.files) ||
      value.files.length > MAX_FILES
    )
      return undefined;
    const files: unknown[] = value.files;
    const entries: [string, OutputFile][] = [];
    const paths = new Set<string>();
    for (const file of files) {
      if (
        typeof file !== "object" ||
        file === null ||
        !("path" in file) ||
        typeof file.path !== "string" ||
        !file.path.startsWith("outputs/") ||
        normalizePanelPath(file.path) !== file.path ||
        paths.has(file.path) ||
        !("revision" in file) ||
        typeof file.revision !== "string" ||
        !file.revision ||
        !("size" in file) ||
        typeof file.size !== "number" ||
        !Number.isSafeInteger(file.size) ||
        file.size < 0
      )
        return undefined;
      paths.add(file.path);
      entries.push([
        file.path,
        { path: file.path, revision: file.revision, size: file.size },
      ]);
    }
    return Object.fromEntries(entries);
  } catch {
    return undefined;
  }
}

export function saveOutputInventorySnapshot(
  userId: string,
  sessionId: string,
  files: Record<string, OutputFile>
): void {
  if (typeof window === "undefined") return;
  try {
    const entries = Object.values(files);
    const serialized = JSON.stringify({ readAt: Date.now(), files: entries });
    if (entries.length > MAX_FILES || serialized.length > MAX_CHARACTERS) {
      window.sessionStorage.removeItem(storageKey(userId, sessionId));
      return;
    }
    window.sessionStorage.setItem(storageKey(userId, sessionId), serialized);
  } catch {
    // A failed replacement must not leave an older snapshot behind.
    clearOutputInventorySnapshot(userId, sessionId);
  }
}

export function clearOutputInventorySnapshot(
  userId: string,
  sessionId: string
): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(storageKey(userId, sessionId));
  } catch {
    // Browser storage can be disabled.
  }
}
