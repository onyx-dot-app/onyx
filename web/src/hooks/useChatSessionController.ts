"use client";

import { useEffect, useCallback, useState } from "react";
import { ReadonlyURLSearchParams } from "next/navigation";
import {
  nameChatSession,
  processRawChatHistory,
  patchMessageToBeLatest,
  resumeStream,
} from "@/app/app/services/lib";
import { Packet } from "@/app/app/services/streamingModels";
import {
  getLatestMessageChain,
  setMessageAsLatest,
} from "@/app/app/services/messageTree";
import {
  BackendChatSession,
  ChatSessionSharedStatus,
  Message,
} from "@/app/app/interfaces";
import {
  SEARCH_PARAM_NAMES,
  shouldSubmitOnLoad,
} from "@/app/app/services/searchParams";
import { FilterManager } from "@/lib/hooks";
import { OnyxDocument } from "@/lib/search/interfaces";
import {
  useChatSessionStore,
  useCurrentMessageHistory,
} from "@/app/app/stores/useChatSessionStore";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import type { ProjectFile } from "@/lib/projects/types";
import {
  getSessionProjectTokenCount,
  getProjectFilesForSession,
} from "@/lib/projects/svc";
import { AppInputBarHandle } from "@/sections/input/AppInputBar";

// Runs currently being re-attached; module-level so effect re-runs (incl.
// strict mode) can't start a second tail for the same run.
const resumingRuns = new Set<number>();

interface UseChatSessionControllerProps {
  existingChatSessionId: string | null;
  searchParams: ReadonlyURLSearchParams;
  filterManager: FilterManager;
  firstMessage?: string;

  // UI state setters
  setSelectedAgentFromId: (agentId: number | null) => void;
  setSelectedDocuments: (documents: OnyxDocument[]) => void;
  setCurrentMessageFiles: (
    files: ProjectFile[] | ((prev: ProjectFile[]) => ProjectFile[])
  ) => void;

  // Refs
  chatSessionIdRef: React.RefObject<string | null>;
  loadedIdSessionRef: React.RefObject<string | null>;
  chatInputBarRef: React.RefObject<AppInputBarHandle | null>;
  isInitialLoad: React.RefObject<boolean>;
  submitOnLoadPerformed: React.RefObject<boolean>;

  // Actions
  refreshChatSessions: () => void;
  onSubmit: (params: {
    message: string;
    currentMessageFiles: ProjectFile[];
    deepResearch: boolean;
    isSeededChat?: boolean;
  }) => Promise<void>;
}

export type SessionFetchError = {
  type: "not_found" | "access_denied" | "unknown";
  detail: string;
} | null;

export default function useChatSessionController({
  existingChatSessionId,
  searchParams,
  filterManager,
  firstMessage,
  setSelectedAgentFromId,
  setSelectedDocuments,
  setCurrentMessageFiles,
  chatSessionIdRef,
  loadedIdSessionRef,
  chatInputBarRef,
  isInitialLoad,
  submitOnLoadPerformed,
  refreshChatSessions,
  onSubmit,
}: UseChatSessionControllerProps) {
  const [currentSessionFileTokenCount, setCurrentSessionFileTokenCount] =
    useState<number>(0);
  const [projectFiles, setProjectFiles] = useState<ProjectFile[]>([]);
  const [sessionFetchError, setSessionFetchError] =
    useState<SessionFetchError>(null);
  // Store actions
  const updateSessionAndMessageTree = useChatSessionStore(
    (state) => state.updateSessionAndMessageTree
  );
  const updateSessionMessageTree = useChatSessionStore(
    (state) => state.updateSessionMessageTree
  );
  const setIsFetchingChatMessages = useChatSessionStore(
    (state) => state.setIsFetchingChatMessages
  );
  const setCurrentSession = useChatSessionStore(
    (state) => state.setCurrentSession
  );
  const initializeSession = useChatSessionStore(
    (state) => state.initializeSession
  );
  const updateCurrentChatSessionSharedStatus = useChatSessionStore(
    (state) => state.updateCurrentChatSessionSharedStatus
  );
  const updateCurrentSelectedNodeForDocDisplay = useChatSessionStore(
    (state) => state.updateCurrentSelectedNodeForDocDisplay
  );
  const currentChatState = useChatSessionStore(
    (state) =>
      state.sessions.get(state.currentSessionId || "")?.chatState || "input"
  );
  const currentChatHistory = useCurrentMessageHistory();
  const chatSessions = useChatSessionStore((state) => state.sessions);
  const { setForcedToolIds } = useForcedTools();

  // Fetch chat messages for the chat session
  useEffect(() => {
    const priorChatSessionId = chatSessionIdRef.current;
    const loadedSessionId = loadedIdSessionRef.current;
    chatSessionIdRef.current = existingChatSessionId;
    loadedIdSessionRef.current = existingChatSessionId;

    chatInputBarRef.current?.focus();

    const isCreatingNewSession =
      priorChatSessionId === null && existingChatSessionId !== null;
    const isSwitchingBetweenSessions =
      priorChatSessionId !== null &&
      existingChatSessionId !== priorChatSessionId;

    // Clear uploaded files on any session change (they're already in context)
    if (isCreatingNewSession || isSwitchingBetweenSessions) {
      setCurrentMessageFiles([]);
    }

    // Only reset filters/selections when switching between existing sessions
    if (isSwitchingBetweenSessions) {
      setSelectedDocuments([]);
      filterManager.setSelectedDocumentSets([]);
      filterManager.setSelectedTags([]);
      filterManager.setTimeRange(null);

      // Remove uploaded files
      setCurrentMessageFiles([]);

      // If switching from one chat to another, then need to scroll again
      // If we're creating a brand new chat, then don't need to scroll
      if (priorChatSessionId !== null) {
        setSelectedDocuments([]);

        // Clear forced tool ids if and only if we're switching to a new chat session
        setForcedToolIds([]);
      }
    }

    async function initialSessionFetch() {
      setSessionFetchError(null);

      if (existingChatSessionId === null) {
        // Clear the current session in the store to show intro messages
        setCurrentSession(null);

        // Reset the selected agent back to default
        setSelectedAgentFromId(null);
        updateCurrentChatSessionSharedStatus(ChatSessionSharedStatus.Private);

        // If we're supposed to submit on initial load, then do that here
        if (
          shouldSubmitOnLoad(searchParams) &&
          !submitOnLoadPerformed.current
        ) {
          submitOnLoadPerformed.current = true;
          await onSubmit({
            message: firstMessage || "",
            currentMessageFiles: [],
            deepResearch: false,
          });
        }
        return;
      }

      // Set the current session first, then set fetching state to prevent intro flash
      setCurrentSession(existingChatSessionId);
      setIsFetchingChatMessages(existingChatSessionId, true);

      let response: Response;
      try {
        response = await fetch(
          `/api/chat/get-chat-session/${existingChatSessionId}`
        );
      } catch (error) {
        setIsFetchingChatMessages(existingChatSessionId, false);
        console.error("Failed to fetch chat session", {
          chatSessionId: existingChatSessionId,
          error,
        });
        setSessionFetchError({
          type: "unknown",
          detail: "Failed to load chat session. Please check your connection.",
        });
        return;
      }

      if (!response.ok) {
        setIsFetchingChatMessages(existingChatSessionId, false);
        let detail = "An unexpected error occurred.";
        try {
          const errorBody = await response.json();
          detail = errorBody.detail || detail;
        } catch {
          // ignore parse errors
        }
        const type =
          response.status === 404
            ? "not_found"
            : response.status === 403
              ? "access_denied"
              : "unknown";
        setSessionFetchError({ type, detail });
        return;
      }

      const session = await response.json();
      const chatSession = session as BackendChatSession;
      setSelectedAgentFromId(chatSession.persona_id);

      // Ensure the current session is set to the actual session ID from the response
      setCurrentSession(chatSession.chat_session_id);

      // Initialize session data including personaId
      initializeSession(chatSession.chat_session_id, chatSession);

      const newMessageMap = processRawChatHistory(
        chatSession.messages,
        chatSession.packets
      );
      const newMessageHistory = getLatestMessageChain(newMessageMap);

      // Update message history except for edge where where
      // last message is an error and we're on a new chat.
      // This corresponds to a "renaming" of chat, which occurs after first message
      // stream
      if (
        (newMessageHistory[newMessageHistory.length - 1]?.type !== "error" ||
          loadedSessionId != null) &&
        !(
          currentChatState == "toolBuilding" ||
          currentChatState == "streaming" ||
          currentChatState == "loading"
        )
      ) {
        updateCurrentSelectedNodeForDocDisplay(
          newMessageHistory[newMessageHistory.length - 1]?.nodeId ?? null
        );

        updateSessionAndMessageTree(chatSession.chat_session_id, newMessageMap);
        chatSessionIdRef.current = chatSession.chat_session_id;
      }

      setIsFetchingChatMessages(chatSession.chat_session_id, false);

      // Re-attach to an in-flight run: replay its buffered stream and tail it
      // live instead of leaving a stale placeholder. Single-model only — a
      // multi-model run_id is the user message, not an assistant node, so it
      // fails the node-type check and keeps the refresh-after-completion
      // behavior.
      async function resumeInFlightRun(
        sessionId: string,
        runId: number,
        messageMap: Map<number, Message>
      ) {
        const node = messageMap.get(runId);
        if (!node || resumingRuns.has(runId)) {
          return;
        }
        // Added and deleted in this function only, so an entry can never
        // outlive its tail.
        resumingRuns.add(runId);
        // The reserved row's placeholder text would render above the live
        // timeline.
        node.message = "";
        const accumulated: Packet[] = [];
        let lastFlush = 0;
        let trailingFlush: ReturnType<typeof setTimeout> | null = null;
        // updateSessionAndMessageTree re-points currentSessionId at this
        // session; once the user navigates elsewhere, any further store write
        // from this tail would hijack their new session's sends.
        const stillCurrent = () =>
          useChatSessionStore.getState().currentSessionId === sessionId;
        const flush = () => {
          if (!stillCurrent()) {
            return;
          }
          node.packets = [...accumulated];
          // AgentMessage's memo compares packetCount, not the packets array.
          node.packetCount = accumulated.length;
          updateSessionAndMessageTree(sessionId, new Map(messageMap));
        };
        // handleSSEStream only releases the connection via this signal —
        // bailing out of the loop alone leaves the SSE response open.
        const abortController = new AbortController();
        try {
          for await (const rawPacket of resumeStream(
            sessionId,
            0,
            abortController.signal
          )) {
            if (!stillCurrent()) {
              return;
            }
            if (!Object.hasOwn(rawPacket, "obj")) {
              continue;
            }
            const packet = rawPacket as Packet;
            // Heartbeats are liveness ticks for the stillCurrent check above,
            // not run state — never render them.
            if (packet.obj.type === "chat_heartbeat") {
              continue;
            }
            accumulated.push(packet);
            const now = Date.now();
            if (now - lastFlush >= 100) {
              lastFlush = now;
              flush();
            } else if (trailingFlush === null) {
              // A burst's last packets would otherwise wait for the NEXT
              // packet to render — during quiet phases that's minutes.
              trailingFlush = setTimeout(() => {
                trailingFlush = null;
                lastFlush = Date.now();
                flush();
              }, 120);
            }
          }
        } catch (error) {
          console.error("Failed to resume in-flight run", { runId, error });
        } finally {
          abortController.abort();
          if (trailingFlush !== null) {
            clearTimeout(trailingFlush);
          }
          resumingRuns.delete(runId);
          if (stillCurrent()) {
            flush();
            // Settle final state (message text, citations, documents) from
            // the persisted session.
            try {
              const settledResponse = await fetch(
                `/api/chat/get-chat-session/${sessionId}`
              );
              if (settledResponse.ok && stillCurrent()) {
                const settled =
                  (await settledResponse.json()) as BackendChatSession;
                updateSessionAndMessageTree(
                  sessionId,
                  processRawChatHistory(settled.messages, settled.packets)
                );
              }
            } catch (error) {
              console.error("Post-resume session refresh failed", { error });
            }
          }
        }
      }

      const currentRun = chatSession.current_run;
      if (
        currentRun &&
        newMessageMap.get(currentRun.run_id)?.type === "assistant"
      ) {
        void resumeInFlightRun(
          chatSession.chat_session_id,
          currentRun.run_id,
          newMessageMap
        );
      }

      // Fetch token count for this chat session's project (if any)
      try {
        if (chatSession.chat_session_id) {
          const total = await getSessionProjectTokenCount(
            chatSession.chat_session_id
          );
          setCurrentSessionFileTokenCount(total || 0);
        } else {
          setCurrentSessionFileTokenCount(0);
        }
      } catch (e) {
        setCurrentSessionFileTokenCount(0);
      }

      // Fetch project files for this chat session (if any)
      try {
        if (chatSession.chat_session_id) {
          const files = await getProjectFilesForSession(
            chatSession.chat_session_id
          );
          setProjectFiles(files || []);
        } else {
          setProjectFiles([]);
        }
      } catch (e) {
        setProjectFiles([]);
      }

      // If this is a seeded chat, then kick off the AI message generation
      if (
        newMessageHistory.length === 1 &&
        !submitOnLoadPerformed.current &&
        searchParams?.get(SEARCH_PARAM_NAMES.SEEDED) === "true"
      ) {
        submitOnLoadPerformed.current = true;

        const seededMessage = newMessageHistory[0]?.message;
        if (!seededMessage) {
          return;
        }

        await onSubmit({
          message: seededMessage,
          isSeededChat: true,
          currentMessageFiles: [],
          deepResearch: false,
        });
        // Force re-name if the chat session doesn't have one
        if (!chatSession.description) {
          await nameChatSession(existingChatSessionId);
          refreshChatSessions();
        }
      } else if (newMessageHistory.length >= 2 && !chatSession.description) {
        await nameChatSession(existingChatSessionId);
        refreshChatSessions();
      }
    }

    // SKIP_RELOAD is used after completing the first message in a new session.
    // We don't need to re-fetch at that point, we have everything we need.
    // For safety, we should always re-fetch if there are no messages in the chat history.
    if (
      !searchParams?.get(SEARCH_PARAM_NAMES.SKIP_RELOAD) ||
      currentChatHistory.length === 0
    ) {
      const existingChatSession = existingChatSessionId
        ? chatSessions.get(existingChatSessionId)
        : null;

      if (
        !existingChatSession?.chatState ||
        existingChatSession.chatState === "input"
      ) {
        initialSessionFetch();
      } else {
        // no need to fetch if the chat session is currently streaming (it would be )
        // out of date).
        // this means that the user kicked off a message, switched to a different
        // chat, and then switched back.
        setCurrentSession(existingChatSessionId);
      }
    } else {
      // Remove SKIP_RELOAD param without triggering a page reload
      const currentSearchParams = new URLSearchParams(searchParams?.toString());
      if (currentSearchParams.has(SEARCH_PARAM_NAMES.SKIP_RELOAD)) {
        currentSearchParams.delete(SEARCH_PARAM_NAMES.SKIP_RELOAD);
        const newUrl = `${window.location.pathname}${
          currentSearchParams.toString()
            ? "?" + currentSearchParams.toString()
            : ""
        }`;
        window.history.replaceState({}, "", newUrl);
      }
    }
  }, [
    existingChatSessionId,
    searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID),
    // Note: We're intentionally not including all dependencies to avoid infinite loops
    // This effect should only run when existingChatSessionId or persona ID changes
  ]);

  const onMessageSelection = useCallback(
    (nodeId: number) => {
      updateCurrentSelectedNodeForDocDisplay(nodeId);
      const currentMessageTree = useChatSessionStore
        .getState()
        .sessions.get(
          useChatSessionStore.getState().currentSessionId || ""
        )?.messageTree;

      if (currentMessageTree) {
        const newMessageTree = setMessageAsLatest(currentMessageTree, nodeId);
        const currentSessionId =
          useChatSessionStore.getState().currentSessionId;
        if (currentSessionId) {
          updateSessionMessageTree(currentSessionId, newMessageTree);
        }

        const message = currentMessageTree.get(nodeId);

        if (message?.messageId) {
          // Makes actual API call to set message as latest in the DB so we can
          // edit this message and so it sticks around on page reload
          patchMessageToBeLatest(message.messageId);
        } else {
          console.error("Message has no messageId", nodeId);
        }
      }
    },
    [updateCurrentSelectedNodeForDocDisplay, updateSessionMessageTree]
  );

  return {
    currentSessionFileTokenCount,
    onMessageSelection,
    projectFiles,
    sessionFetchError,
  };
}
