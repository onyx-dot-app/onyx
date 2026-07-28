"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_PREFIX = "onyx:draft";

export function draftKey(scope: string, entityId: string): string {
  return `${STORAGE_PREFIX}:${scope}:${entityId}`;
}

function getStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    // sessionStorage access throws when storage is blocked.
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function clearDraft(key: string) {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    // ignore
  }
}

function defaultIsEmpty(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value === "string") return value.trim().length === 0;
  return false;
}

export interface UseDraftOptions<T> {
  key: string;
  debounceMs?: number;
  isEmpty?: (value: T) => boolean;
}

export interface UseDraftReturn<T> {
  draft: T | null;
  // Distinguishes "not read yet" from "read, nothing there".
  loaded: boolean;
  hasDraft: boolean;
  // Debounced; empty values remove the key.
  save: (value: T) => void;
  // Removes immediately and cancels any pending write.
  clear: () => void;
}

export function useDraft<T>({
  key,
  debounceMs = 300,
  isEmpty = defaultIsEmpty,
}: UseDraftOptions<T>): UseDraftReturn<T> {
  // Key-tagged so `loaded` is derived, giving a false->true edge on every key
  // change that consumers rely on to re-seed.
  const [entry, setEntry] = useState<{ key: string; draft: T | null } | null>(
    null
  );
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isEmptyRef = useRef(isEmpty);
  isEmptyRef.current = isEmpty;

  useEffect(() => {
    const storage = getStorage();
    if (!storage) {
      setEntry({ key, draft: null });
      return;
    }
    try {
      const raw = storage.getItem(key);
      setEntry({ key, draft: raw === null ? null : (JSON.parse(raw) as T) });
    } catch {
      setEntry({ key, draft: null });
    }
  }, [key]);

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

  const save = useCallback(
    (value: T) => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        const storage = getStorage();
        if (!storage) return;
        try {
          if (isEmptyRef.current(value)) {
            storage.removeItem(key);
          } else {
            storage.setItem(key, JSON.stringify(value));
          }
        } catch {
          // ignore
        }
      }, debounceMs);
    },
    [key, debounceMs]
  );

  const clear = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    clearDraft(key);
    setEntry({ key, draft: null });
  }, [key]);

  const loaded = entry !== null && entry.key === key;
  const draft = loaded ? entry.draft : null;
  const hasDraft = draft !== null && !isEmptyRef.current(draft);

  return { draft, loaded, hasDraft, save, clear };
}
