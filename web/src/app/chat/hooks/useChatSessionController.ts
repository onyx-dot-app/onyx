"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { ReadonlyURLSearchParams, useRouter } from "next/navigation";
import {
  nameChatSession,
  processRawChatHistory,
  patchMessageToBeLatest,
} from "../services/lib";
import {
  getLatestMessageChain,
  setMessageAsLatest,
} from "../services/messageTree";
import { BackendChatSession, ChatSessionSharedStatus } from "../interfaces";
import {
  SEARCH_PARAM_NAMES,
  shouldSubmitOnLoad,
} from "../services/searchParams";
import { FilterManager } from "@/lib/hooks";
import { OnyxDocument } from "@/lib/search/interfaces";
import {
  useChatSessionStore,
  useCurrentMessageHistory,
} from "../stores/useChatSessionStore";
import { getAvailableContextTokens } from "../services/lib";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { ProjectFile } from "../projects/projectsService";
import { getSessionProjectTokenCount } from "../projects/projectsService";
import { getProjectFilesForSession } from "../projects/projectsService";

interface UseChatSessionControllerProps {
  existingChatSessionId: string | null;
  searchParams: ReadonlyURLSearchParams;
  filterManager: FilterManager;
  firstMessage?: string;

  // UI state setters
  setSelectedAssistantFromId: (assistantId: number | null) => void;
  setSelectedDocuments: (documents: OnyxDocument[]) => void;
  setCurrentMessageFiles: (
    files: ProjectFile[] | ((prev: ProjectFile[]) => ProjectFile[])
  ) => void;

  // Refs
  chatSessionIdRef: React.MutableRefObject<string | null>;
  loadedIdSessionRef: React.MutableRefObject<string | null>;
  textAreaRef: React.RefObject<HTMLTextAreaElement>;
  scrollInitialized: React.MutableRefObject<boolean>;
  isInitialLoad: React.MutableRefObject<boolean>;
  submitOnLoadPerformed: React.MutableRefObject<boolean>;

  // State
  hasPerformedInitialScroll: boolean;

  // Actions
  clientScrollToBottom: (fast?: boolean) => void;
  refreshChatSessions: () => void;
  onSubmit: (params: {
    message: string;
    currentMessageFiles: ProjectFile[];
    useAgentSearch: boolean;
    isSeededChat?: boolean;
  }) => Promise<void>;
}

export function useChatSessionController({
  existingChatSessionId,
  searchParams,
  filterManager,
  firstMessage,
  setSelectedAssistantFromId,
  setSelectedDocuments,
  setCurrentMessageFiles,
  chatSessionIdRef,
  loadedIdSessionRef,
  textAreaRef,
  scrollInitialized,
  isInitialLoad,
  submitOnLoadPerformed,
  hasPerformedInitialScroll,
  clientScrollToBottom,
  refreshChatSessions,
  onSubmit,
}: UseChatSessionControllerProps) {
  const [currentSessionFileTokenCount, setCurrentSessionFileTokenCount] =
    useState<number>(0);
  const [projectFiles, setProjectFiles] = useState<ProjectFile[]>([]);
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
  const updateHasPerformedInitialScroll = useChatSessionStore(
    (state) => state.updateHasPerformedInitialScroll
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
  const { setForcedToolIds } = useAgentsContext();

  // Fetch chat messages for the chat session
  useEffect(() => {
    const priorChatSessionId = chatSessionIdRef.current;
    const loadedSessionId = loadedIdSessionRef.current;
    chatSessionIdRef.current = existingChatSessionId;
    loadedIdSessionRef.current = existingChatSessionId;

    textAreaRef.current?.focus();

    // Only clear things if we're going from one chat session to another
    const isChatSessionSwitch = existingChatSessionId !== priorChatSessionId;
    if (isChatSessionSwitch) {
      // De-select documents
      // Reset all filters
      filterManager.setSelectedDocumentSets([]);
      filterManager.setSelectedSources([]);
      filterManager.setSelectedTags([]);
      filterManager.setTimeRange(null);

      // Remove uploaded files
      setCurrentMessageFiles([]);

      // If switching from one chat to another, then need to scroll again
      // If we're creating a brand new chat, then don't need to scroll
      if (priorChatSessionId !== null) {
        setSelectedDocuments([]);
        if (existingChatSessionId) {
          updateHasPerformedInitialScroll(existingChatSessionId, false);
        }

        // Clear forced tool ids if and only if we're switching to a new chat session
        setForcedToolIds([]);
      }
    }

    async function initialSessionFetch() {
      if (existingChatSessionId === null) {
        // Clear the current session in the store to show intro messages
        setCurrentSession(null);

        // Reset the selected assistant back to default
        setSelectedAssistantFromId(null);
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
            useAgentSearch: false,
          });
        }
        return;
      }

      // Set the current session first, then set fetching state to prevent intro flash
      setCurrentSession(existingChatSessionId);
      setIsFetchingChatMessages(existingChatSessionId, true);

      const response = await fetch(
        `/api/chat/get-chat-session/${existingChatSessionId}`
      );

      const session = await response.json();
      const chatSession = session as BackendChatSession;
      setSelectedAssistantFromId(chatSession.persona_id);

      // Ensure the current session is set to the actual session ID from the response
      setCurrentSession(chatSession.chat_session_id);

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

      // Go to bottom. If initial load, then do a scroll,
      // otherwise just appear at the bottom
      scrollInitialized.current = false;

      if (!hasPerformedInitialScroll) {
        if (isInitialLoad.current) {
          if (chatSession.chat_session_id) {
            updateHasPerformedInitialScroll(chatSession.chat_session_id, true);
          }
          isInitialLoad.current = false;
        }
        clientScrollToBottom();

        setTimeout(() => {
          if (chatSession.chat_session_id) {
            updateHasPerformedInitialScroll(chatSession.chat_session_id, true);
          }
        }, 100);
      } else if (isChatSessionSwitch) {
        if (chatSession.chat_session_id) {
          updateHasPerformedInitialScroll(chatSession.chat_session_id, true);
        }
        clientScrollToBottom(true);
      }

      setIsFetchingChatMessages(chatSession.chat_session_id, false);

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
          useAgentSearch: false,
        });
        // Force re-name if the chat session doesn't have one
        if (!chatSession.description) {
          await nameChatSession(existingChatSessionId);
          refreshChatSessions();
        }
      } else if (newMessageHistory.length === 2 && !chatSession.description) {
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
      initialSessionFetch();
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
        .sessions.get(useChatSessionStore.getState().currentSessionId || "")
        ?.messageTree;

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
  };
}
