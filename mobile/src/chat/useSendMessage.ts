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
import { Alert, AppState, type AppStateStatus } from "react-native";
import { fetch as expoFetch } from "expo/fetch";

import { appConfig } from "@/lib/config";
import { FetchError, type ClientConfig } from "@/lib/api";
import {
  streamChatMessage,
  AUTO_PLACE_AFTER_LATEST_MESSAGE,
  type SendMessageRequest,
} from "@/lib/api/sendMessage";
import type { Packet, FileDescriptor } from "@/lib/types";
import { useChatSessionStore } from "@/state/chatSessionStore";
import {
  buildImmediateMessages,
  getLatestMessageChain,
  getLastSuccessfulMessageId,
  type MessageTreeState,
} from "@/state/messageTree";
import { applyPacket } from "@/state/packetProcessor";
import { getAuthHeaders } from "@/auth";
import { useChatSessionLifecycle } from "./useChatSessionLifecycle";

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

// The backend can emit a top-level error object (not a Packet) when generation fails
// — e.g. `{ error, error_code, is_retryable }`. Detect it so we can surface it in the
// thread instead of silently dropping it (which would leave an empty assistant turn).
function asStreamError(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (
    !("obj" in v) &&
    !("placement" in v) &&
    "error" in v &&
    typeof v.error === "string"
  ) {
    return v.error;
  }
  return null;
}

// Flush cadence fallback when requestAnimationFrame is unavailable. ~50ms keeps the
// list updating smoothly without re-rendering on every token.
const FLUSH_INTERVAL_MS = 50;

export interface UseSendMessageResult {
  /**
   * Send `text` with optional uploaded-file attachments (sent as file_descriptors).
   * `onAccepted` fires once the message is committed to the thread (after the
   * session is created + optimistic insert) — callers clear the composer there so
   * a pre-stream failure (e.g. session creation) never discards the user's input.
   */
  send: (
    text: string,
    files?: FileDescriptor[],
    onAccepted?: () => void
  ) => Promise<void>;
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
  // The session the in-flight stream actually runs under. For a draft chat this
  // becomes the real UUID created mid-send (before the `sessionId` prop catches up
  // on re-render), so background-abort tags pendingRefetch with the right key.
  const activeSessionRef = useRef<string | null>(null);

  // Pending-flush bookkeeping for batched tree writes.
  const dirtyRef = useRef(false);
  const rafRef = useRef<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const store = useChatSessionStore;

  // Lazy session create + backend auto-naming (web parity).
  const { ensureSession, autoNameSession } = useChatSessionLifecycle();

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
    async (
      text: string,
      files: FileDescriptor[] = [],
      onAccepted?: () => void
    ) => {
      const trimmed = text.trim();
      // Allow a files-only message (no text) when attachments are present.
      if (!trimmed && files.length === 0) return;

      // ── Lazy session creation (web parity) ────────────────────────────────
      // No backend session is created on the "New Chat" tap; the first message of a
      // brand-new (draft) chat creates it HERE — before streaming — so we hold a
      // stable UUID up front (no fragile mid-stream re-keying). The hook instance is
      // stable across the resulting currentSession change, so stop()/abort keep
      // working. After the first response completes we ask the backend to auto-title it.
      let activeSessionId = sessionId;
      let createdNewSession = false;
      if (!isUuid(sessionId)) {
        const realId = await ensureSession();
        if (!realId) {
          Alert.alert(
            "Couldn't start chat",
            "Please check your connection and try again.",
          );
          return;
        }
        createdNewSession = true;
        // Carry the model picked while drafting onto the real session, then drop the
        // transient "draft" entry so its model can't leak into the next new chat.
        const draft = store.getState().sessions.get(sessionId);
        store.getState().setCurrentSession(realId);
        if (draft?.selectedModel) {
          store.getState().updateSelectedModel(realId, draft.selectedModel);
        }
        store.getState().removeSession(sessionId);
        activeSessionId = realId;
      }

      // Remember the id the stream runs under (for background-abort refetch keying).
      activeSessionRef.current = activeSessionId;

      const s = store.getState();

      // ── (a) Optimistic insert ────────────────────────────────────────────
      const existing = s.sessions.get(activeSessionId);
      const currentTree: MessageTreeState =
        existing?.messageTree ?? new Map();
      const chain = getLatestMessageChain(currentTree);
      const parent = chain[chain.length - 1];
      // Parent node of the new user message: the latest leaf, or the system root.
      const parentNodeId = parent ? parent.nodeId : -3; // SYSTEM_NODE_ID

      const { initialUserNode, initialAgentNode } = buildImmediateMessages(
        parentNodeId,
        trimmed,
        files
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

      store.getState().updateSessionAndMessageTree(activeSessionId, tree);
      store.getState().updateChatState(activeSessionId, "loading");
      store.getState().setUncaughtError(activeSessionId, null);
      store.getState().setStreamingStartTime(activeSessionId, Date.now());

      // ── (b) AbortController ───────────────────────────────────────────────
      const controller = new AbortController();
      controllerRef.current = controller;
      store.getState().setAbortController(activeSessionId, controller);
      if (mountedRef.current) setIsStreaming(true);

      // The message is now committed to the thread — safe to clear the composer.
      // (If session creation above had failed we returned earlier, preserving input.)
      onAccepted?.();

      // ── Batched tree writes ───────────────────────────────────────────────
      // We mutate a local `tree` synchronously on every packet (cheap immutable map
      // copies) but only push it into the store on a scheduled flush, so the list
      // re-renders per frame, not per token.
      const flush = () => {
        rafRef.current = null;
        if (!dirtyRef.current) return;
        dirtyRef.current = false;
        store.getState().updateSessionMessageTree(activeSessionId, tree);
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

      // The model chosen for this session via the input-bar selector (if any). Web
      // maps model_provider = descriptor.name (the provider *instance* name) and
      // model_version = model_configuration.name.
      const selected = store
        .getState()
        .sessions.get(activeSessionId)?.selectedModel;

      const req: SendMessageRequest = {
        message: trimmed,
        // activeSessionId is always a real UUID here (created above for new chats).
        chat_session_id: activeSessionId,
        parent_message_id: parentMessageId,
        file_descriptors: files,
        llm_override: selected
          ? {
              model_provider: selected.name,
              model_version: selected.modelName,
            }
          : undefined,
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

          // Backend-emitted generation error → render it as an error turn.
          const streamErr = asStreamError(item);
          if (streamErr) {
            const node = tree.get(assistantNodeId);
            if (node) {
              tree = new Map(tree);
              tree.set(assistantNodeId, {
                ...node,
                type: "error",
                message: streamErr,
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
              store.getState().updateChatState(activeSessionId, "streaming");
            }
          }

          tree = applyPacket(tree, item, assistantNodeId);
          scheduleFlush();
        }

        // ── (d) Completion ──────────────────────────────────────────────────
        cancelScheduledFlush();
        // Final synchronous flush so the last tokens land immediately.
        store.getState().updateSessionMessageTree(activeSessionId, tree);
        store.getState().updateChatState(activeSessionId, "input");
        store.getState().setStreamingStartTime(activeSessionId, null);
      } catch (err) {
        cancelScheduledFlush();
        // Flush whatever streamed before the failure.
        store.getState().updateSessionMessageTree(activeSessionId, tree);

        if (isAbortError(err)) {
          // ── (e) Clean user/lifecycle stop ────────────────────────────────
          store.getState().updateChatState(activeSessionId, "input");
          store.getState().setStreamingStartTime(activeSessionId, null);
        } else if (err instanceof FetchError && (err.status === 401 || err.status === 403)) {
          // Surface auth failures for the integrator's auth handler. We leave the
          // turn in place and reset chatState; the integrator's auth layer (which
          // owns token refresh / re-login) reads FetchError.status.
          store.getState().updateChatState(activeSessionId, "input");
          store.getState().setStreamingStartTime(activeSessionId, null);
          store
            .getState()
            .setUncaughtError(activeSessionId, `auth_error:${err.status}`);
        } else {
          const message =
            err instanceof Error ? err.message : "Something went wrong.";
          store.getState().updateChatState(activeSessionId, "input");
          store.getState().setStreamingStartTime(activeSessionId, null);
          store.getState().setUncaughtError(activeSessionId, message);
        }
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
        if (mountedRef.current) setIsStreaming(false);

        // First message of a new chat reached a terminal state → let the backend
        // auto-title it (web parity: web names after the try/catch, so a stopped or
        // errored first stream still gets titled instead of stranded as "New Chat").
        if (createdNewSession) {
          void autoNameSession(activeSessionId);
        }
      }
    },
    [
      sessionId,
      config,
      store,
      cancelScheduledFlush,
      ensureSession,
      autoNameSession,
    ]
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
        // Key the flag to the session the stream actually runs under (the real UUID
        // for a draft chat whose creation outran the `sessionId` prop re-render).
        pendingRefetch.add(activeSessionRef.current ?? sessionId);
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
