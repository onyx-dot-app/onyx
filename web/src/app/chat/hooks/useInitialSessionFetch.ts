import { useEffect } from "react";
import { ReadonlyURLSearchParams } from "next/navigation";
import { Persona } from "../../admin/assistants/interfaces";
import {
  Message,
  ChatSessionSharedStatus,
  FileDescriptor,
} from "../interfaces";
import { SEARCH_PARAM_NAMES, shouldSubmitOnLoad } from "../searchParams";
import { processRawChatHistory, buildLatestMessageChain } from "../lib";

export interface UseInitialSessionFetchDependencies {
  // Session state
  existingChatSessionId: string | null;
  defaultAssistantId: number | undefined;
  searchParams: ReadonlyURLSearchParams | null;

  // Refs
  chatSessionIdRef: React.MutableRefObject<string | null>;
  loadedIdSessionRef: React.MutableRefObject<string | null>;
  textAreaRef: React.RefObject<HTMLTextAreaElement>;
  isInitialLoad: React.MutableRefObject<boolean>;
  submitOnLoadPerformed: React.MutableRefObject<boolean>;

  // State setters
  setIsFetchingChatMessages: (fetching: boolean) => void;
  setSelectedAssistantFromId: (assistantId: number) => void;
  setSelectedAssistant: (assistant: Persona | undefined) => void;
  updateCompleteMessageDetail: (
    sessionId: string | null,
    messageMap: Map<number, Message>
  ) => void;
  setChatSessionSharedStatus: (status: ChatSessionSharedStatus) => void;
  setSelectedMessageForDocDisplay: (messageId: number | null) => void;
  setHasPerformedInitialScroll: (performed: boolean) => void;

  // UI state
  hasPerformedInitialScroll: boolean;
  messageHistory: Message[];
  getCurrentChatAnswering: () => boolean;

  // Functions
  clientScrollToBottom: (fast?: boolean) => void;
  onSubmit: (params?: any) => Promise<void>;
  nameChatSession: (sessionId: string) => Promise<void>;
  refreshChatSessions: () => void;

  // Filter management
  filterManager: any;
  setCurrentMessageFiles: (files: FileDescriptor[]) => void;
  clearSelectedDocuments: () => void;

  // Available assistants
  availableAssistants: Persona[];
}

// NOTE: There is probably more "session fetch" logic that can be extracted into a service, which might
//       be better organized into some combined utilities or service (maybe even brought into sessionManager)
export function useInitialSessionFetch(
  deps: UseInitialSessionFetchDependencies
) {
  useEffect(() => {
    const priorChatSessionId = deps.chatSessionIdRef.current;
    const loadedSessionId = deps.loadedIdSessionRef.current;
    deps.chatSessionIdRef.current = deps.existingChatSessionId;
    deps.loadedIdSessionRef.current = deps.existingChatSessionId;

    deps.textAreaRef.current?.focus();

    // only clear things if we're going from one chat session to another
    const isChatSessionSwitch =
      deps.existingChatSessionId !== priorChatSessionId;
    if (isChatSessionSwitch) {
      // de-select documents

      // reset all filters
      deps.filterManager.setSelectedDocumentSets([]);
      deps.filterManager.setSelectedSources([]);
      deps.filterManager.setSelectedTags([]);
      deps.filterManager.setTimeRange(null);

      // remove uploaded files
      deps.setCurrentMessageFiles([]);

      // if switching from one chat to another, then need to scroll again
      // if we're creating a brand new chat, then don't need to scroll
      if (deps.chatSessionIdRef.current !== null) {
        deps.clearSelectedDocuments();
        deps.setHasPerformedInitialScroll(false);
      }
    }

    async function initialSessionFetch() {
      if (deps.existingChatSessionId === null) {
        deps.setIsFetchingChatMessages(false);
        if (deps.defaultAssistantId !== undefined) {
          deps.setSelectedAssistantFromId(deps.defaultAssistantId);
        } else {
          deps.setSelectedAssistant(undefined);
        }
        deps.updateCompleteMessageDetail(null, new Map());
        deps.setChatSessionSharedStatus(ChatSessionSharedStatus.Private);

        // if we're supposed to submit on initial load, then do that here
        if (
          shouldSubmitOnLoad(deps.searchParams) &&
          !deps.submitOnLoadPerformed.current
        ) {
          deps.submitOnLoadPerformed.current = true;
          await deps.onSubmit();
        }
        return;
      }

      deps.setIsFetchingChatMessages(true);
      const response = await fetch(
        `/api/chat/get-chat-session/${deps.existingChatSessionId}`
      );

      const session = await response.json();
      const chatSession = session as any; // BackendChatSession type
      deps.setSelectedAssistantFromId(chatSession.persona_id);

      const newMessageMap = processRawChatHistory(chatSession.messages);
      const newMessageHistory = buildLatestMessageChain(newMessageMap);

      // Update message history except for edge where where
      // last message is an error and we're on a new chat.
      // This corresponds to a "renaming" of chat, which occurs after first message
      // stream
      if (
        (deps.messageHistory[deps.messageHistory.length - 1]?.type !==
          "error" ||
          loadedSessionId != null) &&
        !deps.getCurrentChatAnswering()
      ) {
        const latestMessageId =
          newMessageHistory[newMessageHistory.length - 1]?.messageId;

        deps.setSelectedMessageForDocDisplay(
          latestMessageId !== undefined ? latestMessageId : null
        );

        deps.updateCompleteMessageDetail(
          chatSession.chat_session_id,
          newMessageMap
        );
      }

      deps.setChatSessionSharedStatus(chatSession.shared_status);

      // go to bottom. If initial load, then do a scroll,
      // otherwise just appear at the bottom

      // Note: scrollInitialized is managed outside this hook scope

      if (!deps.hasPerformedInitialScroll) {
        if (deps.isInitialLoad.current) {
          deps.setHasPerformedInitialScroll(true);
          deps.isInitialLoad.current = false;
        }
        deps.clientScrollToBottom();

        setTimeout(() => {
          deps.setHasPerformedInitialScroll(true);
        }, 100);
      } else if (isChatSessionSwitch) {
        deps.setHasPerformedInitialScroll(true);
        deps.clientScrollToBottom(true);
      }

      deps.setIsFetchingChatMessages(false);

      // if this is a seeded chat, then kick off the AI message generation
      if (
        newMessageHistory.length === 1 &&
        newMessageHistory[0] !== undefined &&
        !deps.submitOnLoadPerformed.current &&
        deps.searchParams?.get(SEARCH_PARAM_NAMES.SEEDED) === "true"
      ) {
        deps.submitOnLoadPerformed.current = true;
        const seededMessage = newMessageHistory[0].message;
        await deps.onSubmit({
          isSeededChat: true,
          messageOverride: seededMessage,
        });
        // force re-name if the chat session doesn't have one
        if (!chatSession.description) {
          await deps.nameChatSession(deps.existingChatSessionId);
          deps.refreshChatSessions();
        }
      } else if (newMessageHistory.length === 2 && !chatSession.description) {
        await deps.nameChatSession(deps.existingChatSessionId);
        deps.refreshChatSessions();
      }
    }

    initialSessionFetch();
  }, [
    deps.existingChatSessionId,
    deps.searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID),
  ]);
}
