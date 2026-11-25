"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_PREFIX = "onyx:draft";

export function draftKey(scope: string, entityId: string): string {
  return `${STORAGE_PREFIX}:${scope}:${entityId}`;
}

// "local" keeps the draft across reloads and closed tabs.
export type DraftStorage = "session" | "local";

function getStorage(kind: DraftStorage): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    // Storage access throws when storage is blocked.
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function clearDraft(key: string, kind: DraftStorage = "session") {
  const storage = getStorage(kind);
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    // ignore
  }
}

function defaultIsEmpty<T>(value: T): boolean {
  if (value == null) return true;
  if (typeof value === "string") return value.trim().length === 0;
  return false;
}

/** Reads a draft now, also for a page that is not open. */
export function readDraft<T>(
  key: string,
  kind: DraftStorage = "session"
): T | null {
  const storage = getStorage(kind);
  if (!storage) return null;
  try {
    const raw = storage.getItem(key);
    return raw === null ? null : (JSON.parse(raw) as T);
  } catch {
    return null;
  }
}

/** Writes a draft now, also for a page that is not open. Empty values remove the key. */
export function writeDraft<T>(
  key: string,
  value: T,
  isEmpty: (value: T) => boolean = defaultIsEmpty,
  kind: DraftStorage = "session"
) {
  const storage = getStorage(kind);
  if (!storage) return;
  try {
    if (isEmpty(value)) {
      storage.removeItem(key);
    } else {
      storage.setItem(key, JSON.stringify(value));
    }
  } catch {
    // ignore
  }
}

export interface UseDraftOptions<T> {
  key: string | null;
  debounceMs?: number;
  isEmpty?: (value: T) => boolean;
  storage?: DraftStorage;
}

export interface UseDraftReturn<T> {
  draft: T | null;
  // Distinguishes "not read yet" from "read, nothing there".
  loaded: boolean;
  hasDraft: boolean;
  // Debounced unless debounceMs is zero; empty values remove the key.
  save: (value: T) => void;
  // Removes immediately and cancels any pending write.
  clear: () => void;
}

export function useDraft<T>({
  key,
  debounceMs = 300,
  isEmpty = defaultIsEmpty,
  storage = "session",
}: UseDraftOptions<T>): UseDraftReturn<T> {
  // Key-tagged so `loaded` is derived, giving a false->true edge on every key
  // change that consumers rely on to re-seed.
  const [entry, setEntry] = useState<{ key: string; draft: T | null } | null>(
    null
  );
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const writeRef = useRef<(() => void) | null>(null);
  const isEmptyRef = useRef(isEmpty);

  useEffect(() => {
    isEmptyRef.current = isEmpty;
  }, [isEmpty]);

  useEffect(() => {
    setEntry(key === null ? null : { key, draft: readDraft<T>(key, storage) });
  }, [key, storage]);

  // Cancel a pending write on key change/unmount so it can't land under the old
  // key.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [key]);

  // A page unload skips React cleanup, so write the pending value before the
  // timer is lost.
  useEffect(() => {
    const flush = () => {
      if (timerRef.current === null) return;
      clearTimeout(timerRef.current);
      writeRef.current?.();
    };
    window.addEventListener("pagehide", flush);
    return () => window.removeEventListener("pagehide", flush);
  }, []);

  const save = useCallback(
    (value: T) => {
      if (key === null) return;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      const write = () => {
        timerRef.current = null;
        writeDraft(key, value, isEmptyRef.current, storage);
      };
      if (debounceMs === 0) write();
      else {
        writeRef.current = write;
        timerRef.current = setTimeout(write, debounceMs);
      }
    },
    [key, debounceMs, storage]
  );

  const clear = useCallback(() => {
    if (key === null) return;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    clearDraft(key, storage);
    setEntry({ key, draft: null });
  }, [key, storage]);

  const loaded = entry !== null && entry.key === key;
  const draft = loaded ? entry.draft : null;
  const hasDraft = draft !== null && !isEmpty(draft);

  return { draft, loaded, hasDraft, save, clear };
}
