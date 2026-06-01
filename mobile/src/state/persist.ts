// MMKV-backed persistence for the chat session store.
//
// Responsibilities:
//   1. A singleton MMKV instance (react-native-mmkv v4 — there is no `new MMKV()`;
//      v4 exposes the `createMMKV({ id })` factory instead).
//   2. `mmkvStateStorage`: a SYNC zustand `StateStorage` adapter (getItem/setItem/removeItem).
//      MMKV is synchronous, so hydration is synchronous too — no async gate is needed.
//   3. Map-safe (de)serialization. A `Map` can NOT be blindly `JSON.stringify`-d (it
//      serializes to `{}`), so we tag-and-encode every Map as `["__map__", [[k,v],...]]`
//      and rebuild it on read. This is applied recursively, so the per-session
//      `messageTree` (a `Map<number, Message>`) survives a round-trip.
//   4. `chatPersistStorage(version)`: the zustand `persist` options object that wires a SLIM
//      slice (recent N sessions' trees + draft text) through this storage.
import { createMMKV, type MMKV } from "react-native-mmkv";
import type { PersistOptions, StateStorage } from "zustand/middleware";
import type { MessageTreeState } from "./messageTree";
// Type-only import: avoids a runtime import cycle with chatSessionStore.
import type { ChatSessionData } from "./chatSessionStore";
// Shared default-builder. Lives in its own module (it only type-imports
// ChatSessionData from the store), so this value import does NOT reintroduce the
// store↔persist runtime cycle the type-only import above avoids.
import { createInitialSessionData } from "./sessionDefaults";

// ── MMKV singleton ───────────────────────────────────────────────────────────
export const storage: MMKV = createMMKV({ id: "onyx.chat" });

// ── Map-safe (de)serialization ────────────────────────────────────────────────
// Sentinel tag distinguishing an encoded Map from a normal array/object.
const MAP_TAG = "__map__";

type EncodedMap = [typeof MAP_TAG, [unknown, unknown][]];

function isEncodedMap(value: unknown): value is EncodedMap {
  return (
    Array.isArray(value) && value.length === 2 && value[0] === MAP_TAG
  );
}

// Recursively replace every Map with its tagged-array encoding so JSON.stringify
// can round-trip it. Plain objects/arrays are walked; primitives pass through.
function encodeMaps(value: unknown): unknown {
  if (value instanceof Map) {
    return [
      MAP_TAG,
      Array.from(value.entries()).map(([k, v]) => [encodeMaps(k), encodeMaps(v)]),
    ] satisfies EncodedMap;
  }
  if (Array.isArray(value)) {
    return value.map(encodeMaps);
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = encodeMaps(v);
    }
    return out;
  }
  return value;
}

// Inverse of encodeMaps: rebuild Maps from their tagged encoding.
function decodeMaps(value: unknown): unknown {
  if (isEncodedMap(value)) {
    const entries = value[1].map(
      ([k, v]) => [decodeMaps(k), decodeMaps(v)] as [unknown, unknown]
    );
    return new Map(entries);
  }
  if (Array.isArray(value)) {
    return value.map(decodeMaps);
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = decodeMaps(v);
    }
    return out;
  }
  return value;
}

/** Map-aware JSON.stringify. Safe to call on values containing nested `Map`s. */
export function serializeWithMaps(value: unknown): string {
  return JSON.stringify(encodeMaps(value));
}

/** Map-aware JSON.parse. Reconstructs any `Map`s encoded by `serializeWithMaps`. */
export function deserializeWithMaps<T = unknown>(text: string): T {
  return decodeMaps(JSON.parse(text)) as T;
}

// ── zustand StateStorage adapter (sync) ───────────────────────────────────────
// MMKV's getString returns `string | undefined`; zustand's StateStorage contract
// wants `string | null`, so we coalesce.
// The inferred (narrow) return type is intentionally NOT annotated as
// `StateStorage`: its concrete sync return types (`string | null` / `void`) make
// it assignable to BOTH zustand's `StateStorage` (below) and the React Query
// sync-storage persister's stricter `Storage` shape (used in @/query/client).
/** Build a sync zustand `StateStorage` adapter over any MMKV instance. */
export function makeMmkvStateStorage(mmkv: MMKV) {
  return {
    getItem: (name: string) => mmkv.getString(name) ?? null,
    setItem: (name: string, value: string) => {
      mmkv.set(name, value);
    },
    removeItem: (name: string) => {
      mmkv.remove(name);
    },
  };
}

export const mmkvStateStorage: StateStorage = makeMmkvStateStorage(storage);

// ── Slim persisted slice ──────────────────────────────────────────────────────
// We only persist what's useful to rehydrate offline: the current session id and,
// for the most-recently-accessed N sessions, their messageTree + draft text. We
// deliberately DROP non-serializable / volatile fields (AbortController, queued
// messages, streaming flags, etc.) — they are re-created fresh on load.
const MAX_PERSISTED_SESSIONS = 15;

/** Bumping this invalidates previously-persisted state on schema changes. */
export const PERSIST_VERSION = 1;

// The shape we actually write to disk for each session. Mirrors enough of
// ChatSessionData that `merge` can rebuild a full ChatSessionData on load.
interface PersistedSessionSlice {
  sessionId: string;
  messageTree: MessageTreeState;
  submittedMessage: string;
  description?: string;
  personaId?: number;
  lastAccessedMs: number;
}

interface PersistedState {
  currentSessionId: string | null;
  sessions: Map<string, PersistedSessionSlice>;
}

// The minimum surface `persist` needs from the store. Keeping this local avoids a
// runtime dependency on the (large) store module — we only need these fields to
// build/merge the slice.
interface ChatStoreSnapshot {
  currentSessionId: string | null;
  sessions: Map<string, ChatSessionData>;
}

function buildSlice(state: ChatStoreSnapshot): PersistedState {
  // Keep only the N most-recently-accessed sessions.
  const recent = Array.from(state.sessions.entries())
    .sort(
      ([, a], [, b]) => b.lastAccessed.getTime() - a.lastAccessed.getTime()
    )
    .slice(0, MAX_PERSISTED_SESSIONS);

  const sessions = new Map<string, PersistedSessionSlice>();
  for (const [id, s] of recent) {
    sessions.set(id, {
      sessionId: s.sessionId,
      // messageTree is a Map<number, Message>; serializeWithMaps handles it.
      messageTree: s.messageTree,
      submittedMessage: s.submittedMessage,
      description: s.description,
      personaId: s.personaId,
      lastAccessedMs: s.lastAccessed.getTime(),
    });
  }

  return { currentSessionId: state.currentSessionId, sessions };
}

// Rebuild a full ChatSessionData from a persisted slice, restoring fresh volatile
// fields. Reuses the store's shared default-builder (createInitialSessionData) and
// overrides only the persisted fields, so the two no longer drift apart when a
// ChatSessionData field is added.
function reviveSessionData(slice: PersistedSessionSlice): ChatSessionData {
  return createInitialSessionData(slice.sessionId, {
    messageTree: slice.messageTree ?? new Map(),
    submittedMessage: slice.submittedMessage ?? "",
    description: slice.description,
    personaId: slice.personaId,
    lastAccessed: new Date(slice.lastAccessedMs ?? Date.now()),
    isLoaded: false,
  });
}

/**
 * zustand `persist` options for the chat session store. Wires the slim slice
 * through MMKV with Map-aware (de)serialization.
 *
 * The generic is intentionally loose (`any` for the persisted shape) because
 * zustand's `partialize`/`merge` are typed against the full store state while we
 * intentionally read/write a reduced shape; the casts below are localized here so
 * the store file stays a faithful verbatim port.
 */
export function chatPersistStorage<S extends ChatStoreSnapshot>(
  version: number
): PersistOptions<S, PersistedState> {
  return {
    name: "onyx.chat.sessions",
    version,
    storage: {
      getItem: (name) => {
        const raw = mmkvStateStorage.getItem(name);
        if (raw == null) return null;
        // Returns the standard { state, version } envelope; our Map decoder runs
        // recursively over the whole thing, reviving messageTree Maps.
        return deserializeWithMaps(raw as string);
      },
      setItem: (name, value) => {
        mmkvStateStorage.setItem(name, serializeWithMaps(value));
      },
      removeItem: (name) => {
        mmkvStateStorage.removeItem(name);
      },
    },
    // Only persist the slim slice.
    partialize: (state) => buildSlice(state),
    // Rebuild full ChatSessionData for each persisted session on hydration.
    merge: (persisted, current) => {
      const p = persisted as PersistedState | undefined;
      if (!p || !(p.sessions instanceof Map)) {
        return current;
      }
      const revived = new Map<string, ChatSessionData>();
      for (const [id, slice] of p.sessions) {
        revived.set(id, reviveSessionData(slice));
      }
      return {
        ...current,
        currentSessionId: p.currentSessionId ?? current.currentSessionId,
        sessions: revived,
      } as S;
    },
  };
}
