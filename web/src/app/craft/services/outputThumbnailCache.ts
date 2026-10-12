import type { Cache, State } from "swr";
import type { FileContentResponse } from "@/app/craft/services/apiServices";

import type { OutputFile } from "@/app/craft/types/streamingTypes";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { FilePreviewResult } from "@/lib/build/types";

const MAX_SAVED_CHARACTERS = 2 * 1024 * 1024;
const MAX_SAVED_ENTRIES = 64;
const MAX_AGE = 30 * 60 * 1000;

interface SavedThumbnail {
  key: string;
  savedAt: number;
  data: FilePreviewResult<FileContentResponse>;
}

// oxlint-disable-next-line anti-slop/no-unknown-parameters -- Validates untrusted browser storage.
function parseThumbnail(value: unknown): SavedThumbnail | null {
  if (
    typeof value !== "object" ||
    value === null ||
    !("key" in value) ||
    typeof value.key !== "string" ||
    !value.key.startsWith("craft-output-thumbnail:") ||
    !("savedAt" in value) ||
    typeof value.savedAt !== "number" ||
    !Number.isFinite(value.savedAt) ||
    value.savedAt > Date.now() ||
    Date.now() - value.savedAt > MAX_AGE ||
    !("data" in value) ||
    typeof value.data !== "object" ||
    value.data === null
  )
    return null;
  const result = value.data;
  if (
    !("identity" in result) ||
    typeof result.identity !== "string" ||
    !("data" in result) ||
    typeof result.data !== "object" ||
    result.data === null
  )
    return null;
  const payload = result.data;
  if (
    !("content" in payload) ||
    typeof payload.content !== "string" ||
    !("mimeType" in payload) ||
    typeof payload.mimeType !== "string" ||
    ("isImage" in payload && typeof payload.isImage !== "boolean") ||
    "error" in payload ||
    "error" in result
  )
    return null;
  try {
    const identity: unknown = JSON.parse(result.identity);
    if (
      !Array.isArray(identity) ||
      identity.length !== 3 ||
      identity[0] !== value.key ||
      typeof identity[1] !== "string" ||
      identity[1].length === 0 ||
      typeof identity[2] !== "number" ||
      !Number.isFinite(identity[2])
    )
      return null;
  } catch {
    return null;
  }
  return {
    key: value.key,
    savedAt: value.savedAt,
    data: {
      identity: result.identity,
      data: {
        content: payload.content,
        mimeType: payload.mimeType,
        ...("isImage" in payload &&
          typeof payload.isImage === "boolean" && { isImage: payload.isImage }),
      },
    },
  };
}

type ThumbnailState = State<FilePreviewResult<FileContentResponse>, Error>;

function thumbnailStorageKey(userId: string) {
  return `onyx:craft:output-thumbnails:v1:${userId}`;
}

function readSavedThumbnails(userId?: string): SavedThumbnail[] {
  if (!userId || typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(thumbnailStorageKey(userId));
    if (!raw || raw.length > MAX_SAVED_CHARACTERS) return [];
    const entries: unknown = JSON.parse(raw);
    if (!Array.isArray(entries) || entries.length > MAX_SAVED_ENTRIES)
      return [];
    const items: unknown[] = entries;
    return items.map(parseThumbnail).filter((entry) => entry !== null);
  } catch {
    return [];
  }
}

function serializeSavedThumbnails(
  entries: Iterable<SavedThumbnail>,
  now: number
) {
  const recent = [...entries]
    .filter((entry) => now - entry.savedAt <= MAX_AGE)
    .slice(-MAX_SAVED_ENTRIES);
  let serialized = JSON.stringify(recent);
  while (serialized.length > MAX_SAVED_CHARACTERS && recent.length) {
    recent.shift();
    serialized = JSON.stringify(recent);
  }
  return serialized;
}

function saveThumbnails(userId: string, serialized: string) {
  if (typeof window === "undefined") return;
  const key = thumbnailStorageKey(userId);
  try {
    window.sessionStorage.setItem(key, serialized);
  } catch {
    // Do not leave an older snapshot after a removal fails to save.
    try {
      window.sessionStorage.removeItem(key);
    } catch {
      /* Storage is unavailable. */
    }
  }
}

interface AcceptedSession {
  sessionId: string | null;
  files?: Record<string, OutputFile> | null;
  complete?: boolean;
}

function acceptsThumbnail(
  session: AcceptedSession | undefined,
  key: string,
  value: ThumbnailState
) {
  if (!session) return true;
  const { sessionId, files, complete } = session;
  if (!sessionId || files === null) return false;
  const prefix = SWR_KEYS.buildSessionOutputThumbnail(sessionId, "");
  if (!key.startsWith(prefix)) return false;
  if (!files) return true;
  const file = files[key.slice(prefix.length)];
  return !(
    (!file && complete) ||
    (file &&
      value.data &&
      value.data.identity !== JSON.stringify([key, file.revision, 0]))
  );
}

/** Owns retained bytes; each SWR boundary gets a separate provider over this private map. */
export function createOutputThumbnailCache(
  maxEntries = 128,
  maxCharacters = 16 * 1024 * 1024,
  userId?: string
) {
  const entries = new Map<string, ThumbnailState>();
  const sizes = new Map<string, number>();
  const saved = new Map<string, SavedThumbnail>();
  let characters = 0;
  let retired = false;
  let acceptedSession: AcceptedSession | undefined;

  function persist() {
    if (userId && !retired)
      saveThumbnails(
        userId,
        serializeSavedThumbnails(saved.values(), Date.now())
      );
  }

  function remove(key: string) {
    characters -= sizes.get(key) ?? 0;
    sizes.delete(key);
    const changed = saved.delete(key);
    entries.delete(key);
    return changed;
  }

  // Restoring a cache during render must never write browser storage.
  function store(key: string, value: ThumbnailState) {
    if (retired || !acceptsThumbnail(acceptedSession, key, value)) return false;
    const entry = parseThumbnail({
      key,
      savedAt: Date.now(),
      data: value.data,
    });
    entries.delete(key);
    characters -= sizes.get(key) ?? 0;
    const previous = saved.get(key);
    saved.delete(key);
    entries.set(key, value);
    if (entry)
      saved.set(
        key,
        previous?.data.identity === entry.data.identity &&
          previous.data.data?.content === entry.data.data?.content &&
          previous.data.data?.mimeType === entry.data.data?.mimeType &&
          previous.data.data?.isImage === entry.data.data?.isImage
          ? previous
          : entry
      );
    const size = value.data?.data?.content.length ?? 0;
    sizes.set(key, size);
    characters += size;
    let changed = previous !== saved.get(key);
    while (entries.size > maxEntries || characters > maxCharacters) {
      const oldest = entries.keys().next().value;
      if (oldest === undefined) break;
      changed = remove(oldest) || changed;
    }
    return changed;
  }

  function set(key: string, value: ThumbnailState) {
    if (store(key, value)) persist();
  }

  function deleteEntry(key: string) {
    const existed = entries.has(key);
    if (remove(key)) persist();
    return existed;
  }

  function clear() {
    const changed = saved.size > 0;
    entries.clear();
    sizes.clear();
    saved.clear();
    characters = 0;
    if (changed) persist();
  }

  function retire() {
    retired = true;
    acceptedSession = undefined;
    clear();
  }

  function activateSession(sessionId: string | null) {
    if (acceptedSession?.sessionId !== sessionId)
      acceptedSession = { sessionId };
  }

  function clearSession(sessionId: string) {
    if (!acceptedSession || acceptedSession.sessionId === sessionId)
      acceptedSession = { sessionId, files: null };
    const prefix = SWR_KEYS.buildSessionOutputThumbnail(sessionId, "");
    let changed = false;
    for (const key of entries.keys())
      if (key.startsWith(prefix)) changed = remove(key) || changed;
    if (changed) persist();
  }

  function reconcileSession(
    sessionId: string,
    files: Record<string, OutputFile>,
    complete = true
  ) {
    acceptedSession = { sessionId, files, complete };
    const prefix = SWR_KEYS.buildSessionOutputThumbnail(sessionId, "");
    let changed = false;
    for (const [key, state] of entries) {
      if (!key.startsWith(prefix)) continue;
      const file = files[key.slice(prefix.length)];
      try {
        const identity: unknown = state.data && JSON.parse(state.data.identity);
        if (
          (!file && complete) ||
          (file && (!Array.isArray(identity) || identity[1] !== file.revision))
        )
          changed = remove(key) || changed;
      } catch {
        changed = remove(key) || changed;
      }
    }
    if (changed) persist();
  }

  const get = (key: string) => entries.get(key);
  const keys = () => entries.keys();
  function createProvider(): Cache<FilePreviewResult<FileContentResponse>> {
    return { get, set, delete: deleteEntry, keys };
  }

  for (const entry of readSavedThumbnails(userId)) {
    store(entry.key, { data: entry.data });
    if (entries.has(entry.key)) saved.set(entry.key, entry);
  }

  return {
    get,
    set,
    keys,
    delete: deleteEntry,
    clear,
    get size() {
      return entries.size;
    },
    createProvider,
    activateSession,
    clearSession,
    reconcileSession,
    retire,
  };
}

export type OutputThumbnailCache = ReturnType<
  typeof createOutputThumbnailCache
>;

interface ThumbnailCacheOwner {
  userId: string | undefined;
  cache: OutputThumbnailCache;
}

let thumbnails: ThumbnailCacheOwner | undefined;

/** Reads an existing owner without changing the committed cache scope. */
export function readOutputThumbnailCache(userId?: string) {
  return thumbnails?.userId === userId ? thumbnails?.cache : undefined;
}

/** Called after commit; abandoned renders cannot replace another user's cache. */
export function retainOutputThumbnailCache(
  userId: string | undefined,
  cache: OutputThumbnailCache
) {
  if (thumbnails?.cache !== cache) {
    thumbnails?.cache.retire();
    thumbnails = { userId, cache };
  }
}
