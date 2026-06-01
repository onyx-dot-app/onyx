// Orchestrates an optimistic, streaming chat send against the Zustand session store.
// Cancellation is never `break` — stop()/unmount/background call controller.abort().
// Packet writes are batched per animation frame so FlashList re-renders at a sane
// cadence instead of once per token.

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
import { useForcedTools } from "@/state/useForcedTools";
import { usePersonas, resolveAgent } from "@/query/personas";
import { useAgentPreferences } from "@/query/agentPreferences";
import { useAvailableSourceStrings } from "@/query/connectors";
import { readEnabledSources } from "@/lib/sources/useSourcePreferences";
import { buildFilters } from "@/lib/sources/sourceMetadata";
import {
  buildImmediateMessages,
  getLatestMessageChain,
  getLastSuccessfulMessageId,
  type MessageTreeState,
} from "@/state/messageTree";
import { applyPacket } from "@/state/packetProcessor";
import { getAuthHeaders } from "@/auth";
import { useChatSessionLifecycle } from "./useChatSessionLifecycle";
import { isUuid } from "./uuid";

// expo/fetch is MANDATORY: the global RN fetch cannot stream. Callers may override.
export const defaultStreamConfig: ClientConfig = {
  baseUrl: appConfig.apiBaseUrl,
  fetchImpl: expoFetch as unknown as typeof fetch,
  getAuthHeaders, // injects `Authorization: Bearer <jwt>` from secure-store
};

// Sessions whose stream was interrupted by backgrounding; the UI re-fetches them on
// foreground rather than resuming the dead socket.
const pendingRefetch = new Set<string>();

export function consumePendingRefetch(sessionId: string): boolean {
  const had = pendingRefetch.has(sessionId);
  pendingRefetch.delete(sessionId);
  return had;
}

// The backend emits a top-level `message_id_info` (not a Packet) carrying the real DB
// message ids; we stamp them onto the optimistic nodes so later ops can key off them.
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

// The backend can emit a top-level error object (not a Packet) when generation fails;
// surface it in the thread instead of leaving an empty assistant turn.
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

// Flush cadence fallback when requestAnimationFrame is unavailable.
const FLUSH_INTERVAL_MS = 50;

export interface UseSendMessageResult {
  // `onAccepted` fires once the message is committed to the thread (post session
  // create + optimistic insert) — callers clear the composer there so a pre-stream
  // failure never discards the user's input.
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

  // In-flight stream controller. Ref so stop()/unmount/background can abort without
  // re-rendering or stale closures.
  const controllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  // Session the stream actually runs under — for a draft this is the real UUID created
  // mid-send, so background-abort tags pendingRefetch with the right key.
  const activeSessionRef = useRef<string | null>(null);

  const dirtyRef = useRef(false);
  const rafRef = useRef<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const store = useChatSessionStore;

  // Lazy session create + backend auto-naming (web parity).
  const { ensureSession, autoNameSession } = useChatSessionLifecycle();

  // Tools / sources / force-tool feed the actions-popover controls into the send.
  // Source prefs are NOT read via useSourcePreferences: that hook holds local state
  // seeded once from MMKV, so a popover instance toggling a source wouldn't be seen
  // here. Instead we mirror the source strings into a ref and call readEnabledSources()
  // at send time against the freshest committed MMKV snapshot.
  const { data: personas } = usePersonas();
  const { data: agentPrefs } = useAgentPreferences();
  const availableSourceStrings = useAvailableSourceStrings();
  const availableSourcesRef = useRef(availableSourceStrings);
  useEffect(() => {
    availableSourcesRef.current = availableSourceStrings;
  }, [availableSourceStrings]);
  const personasRef = useRef(personas);
  useEffect(() => {
    personasRef.current = personas;
  }, [personas]);
  const agentPrefsRef = useRef(agentPrefs);
  useEffect(() => {
    agentPrefsRef.current = agentPrefs;
  }, [agentPrefs]);

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

      // Lazy session creation (web parity): a draft chat's first message creates the
      // backend session HERE, before streaming, so we hold a stable UUID up front
      // (no fragile mid-stream re-keying).
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
        // Carry the drafting model onto the real session, then drop the transient
        // draft so its model can't leak into the next new chat.
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

      // Optimistic insert.
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

      // Wire children/latest links from the parent down to the new user node and make
      // the new branch the latest chain (buildImmediateMessages linked user->assistant).
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

      const controller = new AbortController();
      controllerRef.current = controller;
      store.getState().setAbortController(activeSessionId, controller);
      if (mountedRef.current) setIsStreaming(true);

      // The message is now committed to the thread — safe to clear the composer.
      // (If session creation above had failed we returned earlier, preserving input.)
      onAccepted?.();

      // Mutate the local `tree` synchronously per packet but push into the store only
      // on a scheduled flush, so the list re-renders per frame, not per token.
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

      // Tools / sources / force-tool, read imperatively to avoid stale closures.
      const personaId =
        store.getState().sessions.get(activeSessionId)?.personaId;
      // Resolve with the default-assistant fallback (matches ActionsPopover).
      const agent = resolveAgent(personasRef.current, personaId);
      const disabledToolIds =
        agent !== undefined
          ? (agentPrefsRef.current?.[agent.id]?.disabled_tool_ids ?? [])
          : [];
      // Agent unresolved (personas not yet loaded) → omit allowed_tool_ids so the
      // backend defaults to all tools. Intentional.
      const allowedToolIds = agent
        ? agent.tools
            .filter((t) => !disabledToolIds.includes(t.id))
            .map((t) => t.id)
        : undefined;

      const forcedIds = useForcedTools.getState().forcedToolIds;
      const forcedToolId = forcedIds.length > 0 ? forcedIds[0] : null;

      // Read the freshest committed MMKV snapshot at send time (no cross-instance staleness).
      const internalSearchFilters = buildFilters(
        readEnabledSources(availableSourcesRef.current)
      );

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
        allowed_tool_ids: allowedToolIds,
        forced_tool_id: forcedToolId,
        internal_search_filters: internalSearchFilters,
      };

      let sawFirstPacket = false;

      try {
        for await (const item of streamChatMessage(req, config, controller.signal)) {
          // Stamp real message ids onto the optimistic nodes (one-shot, near start).
          const idInfo = asMessageIdInfo(item);
          if (idInfo) {
            const userNode = tree.get(initialUserNode.nodeId);
            const agentNode = tree.get(assistantNodeId);
            if (
              (userNode && idInfo.user_message_id !== null) ||
              agentNode
            ) {
              tree = new Map(tree);
              if (userNode && idInfo.user_message_id !== null) {
                tree.set(initialUserNode.nodeId, {
                  ...userNode,
                  messageId: idInfo.user_message_id,
                });
              }
              if (agentNode) {
                tree.set(assistantNodeId, {
                  ...agentNode,
                  messageId: idInfo.reserved_assistant_message_id,
                });
              }
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

        cancelScheduledFlush();
        // Final synchronous flush so the last tokens land immediately.
        store.getState().updateSessionMessageTree(activeSessionId, tree);
        store.getState().updateChatState(activeSessionId, "input");
        store.getState().setStreamingStartTime(activeSessionId, null);
        // Forced tool is one-shot (web parity): clear only after a SUCCESSFUL send,
        // not on abort/error where the user likely wants to retry.
        useForcedTools.getState().clearForcedTools();
      } catch (err) {
        cancelScheduledFlush();
        // Flush whatever streamed before the failure.
        store.getState().updateSessionMessageTree(activeSessionId, tree);

        // Every terminal path resets chatState + clock; only the error tag varies.
        // AbortError is a clean stop (no tag). A FetchError 401/403 is surfaced as
        // `auth_error:<status>` for the integrator's auth handler. Else a generic tag.
        store.getState().updateChatState(activeSessionId, "input");
        store.getState().setStreamingStartTime(activeSessionId, null);
        if (!isAbortError(err)) {
          const tag =
            err instanceof FetchError &&
            (err.status === 401 || err.status === 403)
              ? `auth_error:${err.status}`
              : err instanceof Error
                ? err.message
                : "Something went wrong.";
          store.getState().setUncaughtError(activeSessionId, tag);
        }
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
        if (mountedRef.current) setIsStreaming(false);

        // First message of a new chat reached a terminal state → auto-title it. Web
        // names after the try/catch, so a stopped/errored first stream still gets titled.
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

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  // Backgrounding aborts the stream and marks the session for re-fetch on foreground.
  useEffect(() => {
    const onChange = (next: AppStateStatus) => {
      if (
        (next === "background" || next === "inactive") &&
        controllerRef.current
      ) {
        // Key the flag to the session the stream actually runs under (the real UUID
        // for a draft whose creation outran the `sessionId` prop re-render).
        pendingRefetch.add(activeSessionRef.current ?? sessionId);
        controllerRef.current.abort();
      }
    };
    const sub = AppState.addEventListener("change", onChange);
    return () => sub.remove();
  }, [sessionId]);

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

function isAbortError(err: unknown): boolean {
  return (
    !!err &&
    typeof err === "object" &&
    "name" in err &&
    (err as { name?: unknown }).name === "AbortError"
  );
}
