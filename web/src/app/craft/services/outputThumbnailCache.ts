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

/** Bounds retained thumbnail strings independently of directory and viewer caches. */
export class OutputThumbnailCache extends Map<string, ThumbnailState> {
  private readonly sizes = new Map<string, number>();
  private characters = 0;
  private readonly saved = new Map<string, SavedThumbnail>();
  private hydrating = false;
  private retired = false;
  private acceptedSession:
    | {
        sessionId: string | null;
        files?: Record<string, OutputFile> | null;
        complete?: boolean;
      }
    | undefined;

  constructor(
    private readonly maxEntries = 128,
    private readonly maxCharacters = 16 * 1024 * 1024,
    private readonly userId?: string
  ) {
    super();
    if (!userId || typeof window === "undefined") return;
    this.hydrating = true;
    try {
      const raw = window.sessionStorage.getItem(this.storageKey());
      if (raw && raw.length <= MAX_SAVED_CHARACTERS) {
        const entries: unknown = JSON.parse(raw);
        if (Array.isArray(entries) && entries.length <= MAX_SAVED_ENTRIES) {
          const items: unknown[] = entries;
          for (const item of items) {
            const entry = parseThumbnail(item);
            if (entry) {
              this.set(entry.key, { data: entry.data });
              if (super.has(entry.key)) this.saved.set(entry.key, entry);
            }
          }
        }
      }
    } catch {
      /* Storage can be unavailable. */
    }
    this.hydrating = false;
  }

  /** Each mounted SWR boundary owns its subscriptions, while thumbnail bytes survive navigation. */
  createProvider(): Cache<FilePreviewResult<FileContentResponse>> {
    return {
      get: (key) => this.get(key),
      set: (key, value) => this.set(key, value),
      delete: (key) => this.delete(key),
      keys: () => this.keys(),
    };
  }

  private storageKey() {
    return `onyx:craft:output-thumbnails:v1:${this.userId}`;
  }

  private persist() {
    if (
      !this.userId ||
      this.hydrating ||
      this.retired ||
      typeof window === "undefined"
    )
      return;
    const entries = [...this.saved.values()]
      .filter((entry) => Date.now() - entry.savedAt <= MAX_AGE)
      .slice(-MAX_SAVED_ENTRIES);
    let serialized = JSON.stringify(entries);
    while (serialized.length > MAX_SAVED_CHARACTERS && entries.length) {
      entries.shift();
      serialized = JSON.stringify(entries);
    }
    try {
      window.sessionStorage.setItem(this.storageKey(), serialized);
    } catch {
      // Do not leave an older snapshot after a removal fails to save.
      try {
        window.sessionStorage.removeItem(this.storageKey());
      } catch {
        /* Storage is unavailable. */
      }
    }
  }

  retire() {
    this.retired = true;
    this.acceptedSession = undefined;
    super.clear();
    this.sizes.clear();
    this.saved.clear();
    this.characters = 0;
  }

  activateSession(sessionId: string | null) {
    if (this.acceptedSession?.sessionId !== sessionId)
      this.acceptedSession = { sessionId };
  }

  clearSession(sessionId: string) {
    if (!this.acceptedSession || this.acceptedSession.sessionId === sessionId)
      this.acceptedSession = { sessionId, files: null };
    const prefix = SWR_KEYS.buildSessionOutputThumbnail(sessionId, "");
    let changed = false;
    for (const key of this.keys())
      if (key.startsWith(prefix)) changed = this.remove(key) || changed;
    if (changed) this.persist();
  }

  reconcileSession(
    sessionId: string,
    files: Record<string, OutputFile>,
    complete = true
  ) {
    this.acceptedSession = { sessionId, files, complete };
    const prefix = SWR_KEYS.buildSessionOutputThumbnail(sessionId, "");
    let changed = false;
    for (const [key, state] of this) {
      if (!key.startsWith(prefix)) continue;
      const file = files[key.slice(prefix.length)];
      try {
        const identity: unknown = state.data && JSON.parse(state.data.identity);
        if (
          (!file && complete) ||
          (file && (!Array.isArray(identity) || identity[1] !== file.revision))
        )
          changed = this.remove(key) || changed;
      } catch {
        changed = this.remove(key) || changed;
      }
    }
    if (changed) this.persist();
  }

  override set(key: string, value: ThumbnailState): this {
    const entry = parseThumbnail({
      key,
      savedAt: Date.now(),
      data: value.data,
    });
    if (this.retired) return this;
    if (this.acceptedSession) {
      const { sessionId, files, complete } = this.acceptedSession;
      if (!sessionId) return this;
      const prefix = SWR_KEYS.buildSessionOutputThumbnail(sessionId, "");
      if (!key.startsWith(prefix) || files === null) return this;
      if (files) {
        const file = files[key.slice(prefix.length)];
        if (
          (!file && complete) ||
          (file &&
            value.data &&
            value.data.identity !== JSON.stringify([key, file.revision, 0]))
        )
          return this;
      }
    }
    super.delete(key);
    this.characters -= this.sizes.get(key) ?? 0;
    const previous = this.saved.get(key);
    this.saved.delete(key);
    super.set(key, value);
    if (entry)
      this.saved.set(
        key,
        previous?.data.identity === entry.data.identity &&
          previous.data.data?.content === entry.data.data?.content &&
          previous.data.data?.mimeType === entry.data.data?.mimeType &&
          previous.data.data?.isImage === entry.data.data?.isImage
          ? previous
          : entry
      );
    const size = value.data?.data?.content.length ?? 0;
    this.sizes.set(key, size);
    this.characters += size;
    let changed = previous !== this.saved.get(key);
    while (
      this.size > this.maxEntries ||
      this.characters > this.maxCharacters
    ) {
      const oldest = this.keys().next().value;
      if (oldest === undefined) break;
      changed = this.remove(oldest) || changed;
    }
    if (changed) this.persist();
    return this;
  }

  private remove(key: string): boolean {
    this.characters -= this.sizes.get(key) ?? 0;
    this.sizes.delete(key);
    const changed = this.saved.delete(key);
    super.delete(key);
    return changed;
  }

  override delete(key: string): boolean {
    const existed = super.has(key);
    if (this.remove(key)) this.persist();
    return existed;
  }

  override clear(): void {
    const changed = this.saved.size > 0;
    super.clear();
    this.sizes.clear();
    this.characters = 0;
    this.saved.clear();
    if (changed) this.persist();
  }
}

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
