"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// Persists in-progress input to browser storage so it survives navigation and
// unexpected logout, then offers it back for restore on return.

const STORAGE_PREFIX = "onyx:draft";

// Namespaced so the flat per-origin store stays collision-free:
// ``onyx:draft:<scope>:<entityId>``.
export function draftKey(scope: string, entityId: string): string {
  return `${STORAGE_PREFIX}:${scope}:${entityId}`;
}

// Drafts live in ``sessionStorage``: per-tab, self-clearing on tab close, and
// it survives reload and the same-tab login redirect, which is all we need
// today.
function getStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    // Storage access can throw in private-browsing / blocked-cookie modes.
    return null;
  }
}

// Direct removal for callers that know the key but don't render the hook (e.g.
// a save-success path).
export function clearDraft(key: string) {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    // ignore
  }
}

// A value is "empty" (and so not worth persisting) when it's nullish or a
// blank/whitespace-only string. Consumers with richer shapes pass their own.
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
  // True once the read for the current key finishes; lets consumers tell "not
  // read yet" from "read, nothing there" before restoring.
  loaded: boolean;
  hasDraft: boolean;
  // Debounced; empty values remove the key instead of writing.
  save: (value: T) => void;
  // Removes immediately and cancels any pending write.
  clear: () => void;
}

export function useDraft<T>({
  key,
  debounceMs = 300,
  isEmpty = defaultIsEmpty,
}: UseDraftOptions<T>): UseDraftReturn<T> {
  // Tag the read result with its key so ``loaded`` is derived, not separate
  // state. This forces a real false->true ``loaded`` edge on every key change,
  // which consumers rely on to re-seed.
  const [entry, setEntry] = useState<{ key: string; draft: T | null } | null>(
    null
  );
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isEmptyRef = useRef(isEmpty);
  isEmptyRef.current = isEmpty;

  // Read the stored draft whenever the key changes. Effects don't run during
  // SSR, so this never touches storage on the server.
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

  // Cancel a pending write when the key changes (or on unmount) so a debounced
  // save for the previous key can't land after the consumer has moved on.
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
          // ignore quota / serialization errors
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
