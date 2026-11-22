import { normalizePanelPath } from "@/app/craft/types/displayTypes";
import type {
  DirectoryListing,
  FileSystemEntry,
} from "@/app/craft/types/streamingTypes";

const MAX_SNAPSHOT_CHARACTERS = 256_000;
const MAX_DIRECTORIES = 32;
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

interface DirectorySnapshot {
  readAt: number;
  listing: DirectoryListing;
}

function storageKey(userId: string, sessionId: string): string {
  return `onyx:craft:directories:v1:${userId}:${sessionId}`;
}

// oxlint-disable-next-line anti-slop/no-unknown-parameters -- Validates untrusted browser storage at the I/O boundary.
function parseEntry(value: unknown): FileSystemEntry | undefined {
  if (
    typeof value !== "object" ||
    value === null ||
    !("name" in value) ||
    typeof value.name !== "string" ||
    !("path" in value) ||
    typeof value.path !== "string" ||
    !("is_directory" in value) ||
    typeof value.is_directory !== "boolean" ||
    !("size" in value) ||
    (value.size !== null &&
      (typeof value.size !== "number" ||
        !Number.isFinite(value.size) ||
        value.size < 0)) ||
    !("mime_type" in value) ||
    (value.mime_type !== null && typeof value.mime_type !== "string")
  )
    return undefined;
  return {
    name: value.name,
    path: value.path,
    is_directory: value.is_directory,
    size: value.size,
    mime_type: value.mime_type,
  };
}

function readSnapshots(userId: string, sessionId: string): DirectorySnapshot[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(storageKey(userId, sessionId));
    if (!raw || raw.length > MAX_SNAPSHOT_CHARACTERS) return [];
    const value: unknown = JSON.parse(raw);
    if (!Array.isArray(value) || value.length > MAX_DIRECTORIES) return [];
    const snapshots: DirectorySnapshot[] = [];
    const items: unknown[] = value;
    for (const item of items) {
      if (
        typeof item !== "object" ||
        item === null ||
        !("readAt" in item) ||
        typeof item.readAt !== "number" ||
        !Number.isFinite(item.readAt) ||
        item.readAt > Date.now() ||
        Date.now() - item.readAt > MAX_AGE_MS ||
        !("listing" in item) ||
        typeof item.listing !== "object" ||
        item.listing === null ||
        !("path" in item.listing) ||
        typeof item.listing.path !== "string" ||
        (item.listing.path !== "" &&
          normalizePanelPath(item.listing.path) !== item.listing.path) ||
        !("entries" in item.listing) ||
        !Array.isArray(item.listing.entries)
      )
        continue;
      const entries: FileSystemEntry[] = [];
      const storedEntries: unknown[] = item.listing.entries;
      for (const stored of storedEntries) {
        const entry = parseEntry(stored);
        if (
          !entry ||
          entry.path !==
            `${item.listing.path ? `${item.listing.path}/` : ""}${entry.name}` ||
          normalizePanelPath(entry.path) !== entry.path
        )
          return [];
        entries.push(entry);
      }
      snapshots.push({
        readAt: item.readAt,
        listing: { path: item.listing.path, entries },
      });
    }
    return snapshots;
  } catch {
    return [];
  }
}

export function readWorkspaceDirectorySnapshot(
  userId: string,
  sessionId: string,
  path: string
): DirectoryListing | undefined {
  return readSnapshots(userId, sessionId).find(
    (snapshot) => snapshot.listing.path === path
  )?.listing;
}

export function saveWorkspaceDirectorySnapshot(
  userId: string,
  sessionId: string,
  listing: DirectoryListing
): void {
  if (typeof window === "undefined") return;
  try {
    const snapshot = { readAt: Date.now(), listing };
    const snapshots = readSnapshots(userId, sessionId).filter(
      (snapshot) => snapshot.listing.path !== listing.path
    );
    if (JSON.stringify([snapshot]).length <= MAX_SNAPSHOT_CHARACTERS)
      snapshots.push(snapshot);
    let serialized = JSON.stringify(snapshots);
    while (
      snapshots.length > MAX_DIRECTORIES ||
      serialized.length > MAX_SNAPSHOT_CHARACTERS
    ) {
      snapshots.shift();
      serialized = JSON.stringify(snapshots);
    }
    window.sessionStorage.setItem(storageKey(userId, sessionId), serialized);
  } catch {
    // A failed replacement must not leave an older snapshot behind.
    clearWorkspaceDirectorySnapshots(userId, sessionId);
  }
}

export function clearWorkspaceDirectorySnapshots(
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
