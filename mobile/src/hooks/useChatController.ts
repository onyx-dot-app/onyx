// Send → stream → ~50ms batched flush → stop, plus hydration. runChatStream is module-scope so the stream
// keeps writing by sessionId after the landing screen unmounts navigating into /chat/[id].
import { useCallback, useEffect, useMemo, useState } from "react";
import { router } from "expo-router";
import { useQuery } from "@tanstack/react-query";

import { QUERY_KEYS } from "@/api/query-keys";
import {
  createChatSession,
  getChatSession,
  stopChatSession,
} from "@/api/chat/sessions";
import {
  isMessageIdInfo,
  isPacket,
  SendMessageBody,
  streamChatMessage,
} from "@/api/chat/stream";
import { processRawChatHistory } from "@/chat/chatHistory";
import { ChatState } from "@/chat/interfaces";
import {
  buildImmediateMessages,
  getLastSuccessfulMessageId,
  getLatestMessageChain,
  SYSTEM_MESSAGE_ID,
  SYSTEM_NODE_ID,
  upsertMessages,
} from "@/chat/messageTree";
import { Packet } from "@/chat/streamingModels";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useSession } from "@/state/session";

const FLUSH_INTERVAL_MS = 50;

async function runChatStream(
  sessionId: string,
  userNodeId: number,
  agentNodeId: number,
  body: SendMessageBody,
  signal: AbortSignal,
): Promise<void> {
  const store = useChatSessionStore;
  let pending: Packet[] = [];
  let flushTimer: ReturnType<typeof setTimeout> | null = null;
  let sawStreaming = false;

  function flush() {
    if (pending.length === 0) return;
    const data = store.getState().sessions.get(sessionId);
    const node = data?.messageTree.get(agentNodeId);
    if (!data || !node) {
      pending = [];
      return;
    }
    const updatedNode = { ...node, packets: [...node.packets, ...pending] };
    pending = [];
    store
      .getState()
      .updateSessionTree(
        sessionId,
        upsertMessages(data.messageTree, [updatedNode], false),
      );
  }

  function scheduleFlush() {
    if (flushTimer) return;
    flushTimer = setTimeout(() => {
      flushTimer = null;
      flush();
    }, FLUSH_INTERVAL_MS);
  }

  try {
    for await (const event of streamChatMessage(body, signal)) {
      if (signal.aborted) break;
      if (isMessageIdInfo(event)) {
        if (event.user_message_id != null) {
          store.getState().patchNode(sessionId, userNodeId, {
            messageId: event.user_message_id,
          });
        }
        store.getState().patchNode(sessionId, agentNodeId, {
          messageId: event.reserved_assistant_message_id,
        });
        continue;
      }
      if (isPacket(event)) {
        if (!sawStreaming) {
          sawStreaming = true;
          store.getState().updateChatState(sessionId, "streaming");
        }
        pending.push(event);
        scheduleFlush();
      }
    }
  } catch (error) {
    // Abort is the normal stop path; any other failure marks the assistant node errored.
    if (!signal.aborted) {
      const message =
        error instanceof Error ? error.message : "Something went wrong.";
      store.getState().patchNode(sessionId, agentNodeId, {
        type: "error",
        message,
      });
    }
  } finally {
    if (flushTimer) clearTimeout(flushTimer);
    flush();
    store.getState().updateChatState(sessionId, "input");
    store.getState().setAbortController(sessionId, null);
  }
}

export interface ChatController {
  messages: ReturnType<typeof getLatestMessageChain>;
  chatState: ChatState;
  input: string;
  setInput: (value: string) => void;
  submit: () => void;
  stop: () => void;
  isHydrating: boolean;
}

export function useChatController(sessionId: string | null): ChatController {
  const [input, setInput] = useState("");
  const serverUrl = useSession((state) => state.serverUrl);
  const sessionData = useChatSessionStore((state) =>
    sessionId ? state.sessions.get(sessionId) : undefined,
  );

  useEffect(() => {
    if (sessionId) useChatSessionStore.getState().setCurrentSession(sessionId);
  }, [sessionId]);

  // Hydrate a session opened but not yet in the store (sidebar / relaunch).
  const needsHydration = sessionId != null && sessionData === undefined;
  const hydration = useQuery({
    queryKey: QUERY_KEYS.chatSession(serverUrl, sessionId ?? "new"),
    enabled: needsHydration && serverUrl != null,
    queryFn: async () => {
      const backend = await getChatSession(sessionId!);
      // A live stream may have filled the store meanwhile — don't clobber it.
      if (!useChatSessionStore.getState().sessions.has(sessionId!)) {
        useChatSessionStore
          .getState()
          .hydrateSession(
            sessionId!,
            processRawChatHistory(backend.messages, backend.packets),
          );
      }
      return backend;
    },
  });

  const messages = useMemo(
    () => (sessionData ? getLatestMessageChain(sessionData.messageTree) : []),
    [sessionData],
  );
  const chatState: ChatState = sessionData?.chatState ?? "input";

  const submit = useCallback(async () => {
    const text = input.trim();
    if (!text) return;
    // Clear synchronously so a second tap during the create-session await can't double-submit
    // (the input is empty → canSend is false).
    setInput("");

    let activeId = sessionId;
    if (activeId != null) {
      const current = useChatSessionStore.getState().sessions.get(activeId);
      if (current && current.chatState !== "input") return; // a run is already active
    } else {
      activeId = await createChatSession();
    }

    const store = useChatSessionStore.getState();
    store.ensureSession(activeId);
    // Re-read: the captured store.sessions snapshot predates ensureSession.
    const tree =
      useChatSessionStore.getState().sessions.get(activeId)?.messageTree ??
      new Map();
    const chain = getLatestMessageChain(tree);
    const lastNode = chain[chain.length - 1];
    const parentNodeId = lastNode ? lastNode.nodeId : SYSTEM_NODE_ID;
    // -3 (synthetic root) → null; null = first message.
    const lastSuccessful = getLastSuccessfulMessageId(tree);
    const parentMessageId =
      lastSuccessful === SYSTEM_MESSAGE_ID ? null : lastSuccessful;

    const { initialUserNode, initialAgentNode } = buildImmediateMessages(
      parentNodeId,
      text,
      [],
    );
    store.updateSessionTree(
      activeId,
      upsertMessages(tree, [initialUserNode, initialAgentNode], true),
    );
    store.updateChatState(activeId, "loading");
    store.setSubmittedMessage(activeId, text);

    const controller = new AbortController();
    store.setAbortController(activeId, controller);

    const body: SendMessageBody = {
      message: text,
      chat_session_id: activeId,
      parent_message_id: parentMessageId,
      file_descriptors: [],
      deep_research: false,
      origin: "mobile",
    };

    // replace so Back doesn't return to the empty landing
    if (sessionId == null) {
      router.replace({ pathname: "/chat/[id]", params: { id: activeId } });
    }

    void runChatStream(
      activeId,
      initialUserNode.nodeId,
      initialAgentNode.nodeId,
      body,
      controller.signal,
    );
  }, [input, sessionId]);

  const stop = useCallback(() => {
    if (sessionId == null) return;
    useChatSessionStore.getState().abortSession(sessionId);
    // client abort alone leaves the backend generating
    void stopChatSession(sessionId).catch(() => {});
  }, [sessionId]);

  return {
    messages,
    chatState,
    input,
    setInput,
    submit,
    stop,
    isHydrating: needsHydration && hydration.isLoading,
  };
}
