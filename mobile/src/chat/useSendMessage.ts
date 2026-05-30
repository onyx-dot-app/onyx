// useSendMessage.ts — orchestrates an optimistic, streaming chat send against the
// Zustand chat-session store.
//
// Flow of a single send():
//   1. Optimistically insert a user Message + an empty assistant child into the
//      session's messageTree (so the UI shows the turn instantly), chatState="loading".
//   2. Create an AbortController, store it via setAbortController.
//   3. Open the NDJSON stream (streamChatMessage) and iterate it with `for await`.
//      We NEVER `break` to cancel — stop()/unmount/background calls controller.abort(),
//      whose signal cancels the reader inside handleSSEStream.
//   4. Each Packet is reduced into the assistant node via applyPacket. Writes are
//      BATCHED per animation frame (~rAF / ~50ms fallback) so FlashList re-renders at a
//      sane cadence instead of once per token (per doc 06).
//   5. On completion chatState="input"; on AbortError it's a clean user stop; a
//      FetchError 401/403 is surfaced for the integrator's auth handler; anything else
//      becomes an error state on the session.
//
// AppState lifecycle: while streaming, backgrounding the app aborts the stream and sets
// a per-session re-fetch flag (sessionId added to a module-level set, readable via
// `consumePendingRefetch`). We do NOT try to resume the socket — re-fetching the session
// on foreground is doc-06/UI's job. We just abort cleanly and leave the flag.

import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";
import { fetch as expoFetch } from "expo/fetch";

import { appConfig } from "@/lib/config";
import { FetchError, type ClientConfig } from "@/lib/api";
import {
  streamChatMessage,
  AUTO_PLACE_AFTER_LATEST_MESSAGE,
  type SendMessageRequest,
} from "@/lib/api/sendMessage";
import type { Packet } from "@/lib/types";
import { useChatSessionStore } from "@/state/chatSessionStore";
import {
  buildImmediateMessages,
  getLatestMessageChain,
  getLastSuccessfulMessageId,
  type MessageTreeState,
} from "@/state/messageTree";
import { applyPacket } from "@/state/packetProcessor";
import { getAuthHeaders } from "@/auth";

// ── Default transport config ────────────────────────────────────────────────
// appConfig + expo/fetch + the real JWT auth headers (from @/auth), so a send is
// authenticated out of the box. expo/fetch is MANDATORY: the global RN fetch
// cannot stream. Callers may still pass their own `config`.
export const defaultStreamConfig: ClientConfig = {
  baseUrl: appConfig.apiBaseUrl,
  fetchImpl: expoFetch as unknown as typeof fetch,
  getAuthHeaders, // injects `Authorization: Bearer <jwt>` from secure-store
};

// ── Pending re-fetch flags (AppState background handling) ────────────────────
// Sessions whose stream was interrupted by backgrounding. The UI layer calls
// consumePendingRefetch(sessionId) on foreground to decide whether to re-fetch the
// session from the backend (the source of truth) rather than resume the dead socket.
const pendingRefetch = new Set<string>();

/** True (and clears the flag) if `sessionId`'s stream was aborted by backgrounding. */
export function consumePendingRefetch(sessionId: string): boolean {
  const had = pendingRefetch.has(sessionId);
  pendingRefetch.delete(sessionId);
  return had;
}

// ── message_id_info handling ─────────────────────────────────────────────────
// The backend emits a top-level `message_id_info` object near the start of the
// stream carrying the real (DB) user + reserved assistant message ids. It is NOT a
// Packet (no `placement`/`obj`), so applyPacket ignores it. We detect its shape and
// stamp the real messageIds onto our optimistic nodes so later operations (feedback,
// regeneration, re-fetch reconciliation) can key off real ids.
interface MessageIdInfoLike {
  user_message_id: number | null;
  reserved_assistant_message_id: number;
}

function asMessageIdInfo(value: unknown): MessageIdInfoLike | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (
    "reserved_assistant_message_id" in v &&
    typeof v.reserved_assistant_message_id === "number" &&
    "user_message_id" in v
  ) {
    return {
      user_message_id:
        typeof v.user_message_id === "number" ? v.user_message_id : null,
      reserved_assistant_message_id: v.reserved_assistant_message_id,
    };
  }
  return null;
}

function isPacket(value: unknown): value is Packet {
  return (
    !!value &&
    typeof value === "object" &&
    "obj" in (value as Record<string, unknown>) &&
    "placement" in (value as Record<string, unknown>)
  );
}

// Flush cadence fallback when requestAnimationFrame is unavailable. ~50ms keeps the
// list updating smoothly without re-rendering on every token.
const FLUSH_INTERVAL_MS = 50;

export interface UseSendMessageResult {
  send: (text: string) => Promise<void>;
  stop: () => void;
  isStreaming: boolean;
}

export function useSendMessage(
  sessionId: string,
  config: ClientConfig = defaultStreamConfig
): UseSendMessageResult {
  const [isStreaming, setIsStreaming] = useState(false);

  // The controller for the in-flight stream (mirrored into the store too). Kept in a
  // ref so stop()/unmount/background can abort without re-rendering or stale closures.
  const controllerRef = useRef<AbortController | null>(null);
  // Guards against state writes after unmount.
  const mountedRef = useRef(true);

  // Pending-flush bookkeeping for batched tree writes.
  const dirtyRef = useRef(false);
  const rafRef = useRef<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const store = useChatSessionStore;

  const cancelScheduledFlush = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      const s = store.getState();

      // ── (a) Optimistic insert ────────────────────────────────────────────
      const existing = s.sessions.get(sessionId);
      const currentTree: MessageTreeState =
        existing?.messageTree ?? new Map();
      const chain = getLatestMessageChain(currentTree);
      const parent = chain[chain.length - 1];
      // Parent node of the new user message: the latest leaf, or the system root.
      const parentNodeId = parent ? parent.nodeId : -3; // SYSTEM_NODE_ID

      const { initialUserNode, initialAgentNode } = buildImmediateMessages(
        parentNodeId,
        trimmed,
        []
      );

      // Wire children/latest links from the parent down to the new user node, then
      // make the new branch the latest chain. upsertMessages handles the parent's
      // childrenNodeIds + latestChildNodeId; buildImmediateMessages already linked
      // the user->assistant pair.
      let tree = new Map(currentTree);
      tree.set(initialUserNode.nodeId, initialUserNode);
      tree.set(initialAgentNode.nodeId, initialAgentNode);
      const parentMsg = tree.get(parentNodeId);
      if (parentMsg) {
        const children = parentMsg.childrenNodeIds ?? [];
        tree.set(parentNodeId, {
          ...parentMsg,
          childrenNodeIds: children.includes(initialUserNode.nodeId)
            ? children
            : [...children, initialUserNode.nodeId],
          latestChildNodeId: initialUserNode.nodeId,
        });
      }

      // The real parent_message_id for the backend: the last successful (DB-backed)
      // message id in the chain, or -1 to auto-place after the latest message.
      const lastSuccessfulId = getLastSuccessfulMessageId(currentTree);
      const parentMessageId =
        lastSuccessfulId ?? AUTO_PLACE_AFTER_LATEST_MESSAGE;

      const assistantNodeId = initialAgentNode.nodeId;

      store.getState().updateSessionAndMessageTree(sessionId, tree);
      store.getState().updateChatState(sessionId, "loading");
      store.getState().setUncaughtError(sessionId, null);
      store.getState().setStreamingStartTime(sessionId, Date.now());

      // ── (b) AbortController ───────────────────────────────────────────────
      const controller = new AbortController();
      controllerRef.current = controller;
      store.getState().setAbortController(sessionId, controller);
      if (mountedRef.current) setIsStreaming(true);

      // ── Batched tree writes ───────────────────────────────────────────────
      // We mutate a local `tree` synchronously on every packet (cheap immutable map
      // copies) but only push it into the store on a scheduled flush, so the list
      // re-renders per frame, not per token.
      const flush = () => {
        rafRef.current = null;
        if (!dirtyRef.current) return;
        dirtyRef.current = false;
        store.getState().updateSessionMessageTree(sessionId, tree);
      };

      const scheduleFlush = () => {
        dirtyRef.current = true;
        if (typeof requestAnimationFrame === "function") {
          if (rafRef.current === null) {
            rafRef.current = requestAnimationFrame(flush);
          }
        } else if (intervalRef.current === null) {
          intervalRef.current = setInterval(() => {
            flush();
          }, FLUSH_INTERVAL_MS);
        }
      };

      const req: SendMessageRequest = {
        message: trimmed,
        // A brand-new (optimistic-only) session has a non-UUID temp id; treat any
        // non-UUID as "no session yet" so the backend creates one.
        chat_session_id: isUuid(sessionId) ? sessionId : null,
        parent_message_id: parentMessageId,
        file_descriptors: [],
        origin: "unset",
      };

      let sawFirstPacket = false;

      try {
        for await (const item of streamChatMessage(req, config, controller.signal)) {
          // Stamp real message ids onto the optimistic nodes (one-shot, near start).
          const idInfo = asMessageIdInfo(item);
          if (idInfo) {
            const userNode = tree.get(initialUserNode.nodeId);
            if (userNode && idInfo.user_message_id !== null) {
              tree = new Map(tree);
              tree.set(initialUserNode.nodeId, {
                ...userNode,
                messageId: idInfo.user_message_id,
              });
            }
            const agentNode = tree.get(assistantNodeId);
            if (agentNode) {
              tree = new Map(tree);
              tree.set(assistantNodeId, {
                ...agentNode,
                messageId: idInfo.reserved_assistant_message_id,
              });
            }
            scheduleFlush();
            continue;
          }

          if (!isPacket(item)) continue;

          // First real packet => the model is producing output: loading -> streaming.
          if (!sawFirstPacket) {
            sawFirstPacket = true;
            if (mountedRef.current) {
              store.getState().updateChatState(sessionId, "streaming");
            }
          }

          tree = applyPacket(tree, item, assistantNodeId);
          scheduleFlush();
        }

        // ── (d) Completion ──────────────────────────────────────────────────
        cancelScheduledFlush();
        // Final synchronous flush so the last tokens land immediately.
        store.getState().updateSessionMessageTree(sessionId, tree);
        store.getState().updateChatState(sessionId, "input");
        store.getState().setStreamingStartTime(sessionId, null);
      } catch (err) {
        cancelScheduledFlush();
        // Flush whatever streamed before the failure.
        store.getState().updateSessionMessageTree(sessionId, tree);

        if (isAbortError(err)) {
          // ── (e) Clean user/lifecycle stop ────────────────────────────────
          store.getState().updateChatState(sessionId, "input");
          store.getState().setStreamingStartTime(sessionId, null);
        } else if (err instanceof FetchError && (err.status === 401 || err.status === 403)) {
          // Surface auth failures for the integrator's auth handler. We leave the
          // turn in place and reset chatState; the integrator's auth layer (which
          // owns token refresh / re-login) reads FetchError.status.
          store.getState().updateChatState(sessionId, "input");
          store.getState().setStreamingStartTime(sessionId, null);
          store
            .getState()
            .setUncaughtError(sessionId, `auth_error:${err.status}`);
        } else {
          const message =
            err instanceof Error ? err.message : "Something went wrong.";
          store.getState().updateChatState(sessionId, "input");
          store.getState().setStreamingStartTime(sessionId, null);
          store.getState().setUncaughtError(sessionId, message);
        }
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
        if (mountedRef.current) setIsStreaming(false);
      }
    },
    [sessionId, config, store, cancelScheduledFlush]
  );

  // ── stop(): user-initiated cancel ──────────────────────────────────────────
  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  // ── AppState lifecycle: abort + mark for re-fetch on background ─────────────
  useEffect(() => {
    const onChange = (next: AppStateStatus) => {
      if (
        (next === "background" || next === "inactive") &&
        controllerRef.current
      ) {
        // Abort the dead-in-the-water socket and leave a re-fetch flag. We do NOT
        // attempt to resume the stream — the UI re-fetches the session on foreground.
        pendingRefetch.add(sessionId);
        controllerRef.current.abort();
      }
    };
    const sub = AppState.addEventListener("change", onChange);
    return () => sub.remove();
  }, [sessionId]);

  // ── Unmount: abort any in-flight stream + cancel scheduled flushes ──────────
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
      cancelScheduledFlush();
    };
  }, [cancelScheduledFlush]);

  return { send, stop, isStreaming };
}

// ── helpers ──────────────────────────────────────────────────────────────────
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

function isAbortError(err: unknown): boolean {
  return (
    !!err &&
    typeof err === "object" &&
    "name" in err &&
    (err as { name?: unknown }).name === "AbortError"
  );
}
