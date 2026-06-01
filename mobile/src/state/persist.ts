// MMKV-backed persistence for the chat session store.
import { createMMKV, type MMKV } from "react-native-mmkv";
import type { PersistOptions, StateStorage } from "zustand/middleware";
import type { MessageTreeState } from "./messageTree";
// Type-only import: avoids a runtime import cycle with chatSessionStore.
import type { ChatSessionData } from "./chatSessionStore";
import { createInitialSessionData } from "./sessionDefaults";

// react-native-mmkv v4 has no `new MMKV()`; use the createMMKV factory.
export const storage: MMKV = createMMKV({ id: "onyx.chat" });

// A Map can't be JSON.stringify-d (it serializes to `{}`), so we tag-encode every
// Map as `["__map__", [[k,v],...]]` recursively and rebuild it on read, so the
// per-session messageTree (a Map<number, Message>) survives a round-trip.
const MAP_TAG = "__map__";

type EncodedMap = [typeof MAP_TAG, [unknown, unknown][]];

function isEncodedMap(value: unknown): value is EncodedMap {
  return (
    Array.isArray(value) && value.length === 2 && value[0] === MAP_TAG
  );
}

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

export function serializeWithMaps(value: unknown): string {
  return JSON.stringify(encodeMaps(value));
}

export function deserializeWithMaps<T = unknown>(text: string): T {
  return decodeMaps(JSON.parse(text)) as T;
}

// Return type is intentionally NOT annotated as StateStorage: its concrete sync
// types (`string | null` / `void`) make it assignable to BOTH zustand's
// StateStorage and the stricter React Query sync-storage persister Storage shape.
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

// Persist only what's useful offline (current session id + recent N sessions'
// messageTree/draft text). Non-serializable/volatile fields (AbortController,
// queued messages, streaming flags) are deliberately dropped and re-created on load.
const MAX_PERSISTED_SESSIONS = 15;

// Bumping this invalidates previously-persisted state on schema changes.
export const PERSIST_VERSION = 1;

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

// Local minimal store surface — avoids a runtime dependency on the store module.
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
      messageTree: s.messageTree,
      submittedMessage: s.submittedMessage,
      description: s.description,
      personaId: s.personaId,
      lastAccessedMs: s.lastAccessed.getTime(),
    });
  }

  return { currentSessionId: state.currentSessionId, sessions };
}

// Rebuild full ChatSessionData via the shared default-builder, overriding only the
// persisted fields, so the two don't drift when a ChatSessionData field is added.
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

// zustand persist options wiring the slim slice through MMKV with Map-aware
// (de)serialization. The casts below are localized here so the store file stays a
// faithful verbatim port (partialize/merge are typed against the full store state
// while we read/write a reduced shape).
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
        // Map decoder runs recursively over the { state, version } envelope,
        // reviving messageTree Maps.
        return deserializeWithMaps(raw as string);
      },
      setItem: (name, value) => {
        mmkvStateStorage.setItem(name, serializeWithMaps(value));
      },
      removeItem: (name) => {
        mmkvStateStorage.removeItem(name);
      },
    },
    partialize: (state) => buildSlice(state),
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
