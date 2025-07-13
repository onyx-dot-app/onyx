import { RetrievalType } from "../interfaces";
import { buildChatUrl, nameChatSession } from "../lib";
import { ReadonlyURLSearchParams } from "next/navigation";
import { Persona } from "../../admin/assistants/interfaces";
import { BackendMessage } from "../interfaces";
import { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";

export interface PostProcessorDependencies {
  setAgenticGenerating: (generating: boolean) => void;
  resetRegenerationState: (sessionId: string) => void;
  updateChatState: (state: string, sessionId?: string) => void;
  setSelectedMessageForDocDisplay: (messageId: number | null) => void;
  setAlternativeGeneratingAssistant: (assistant: Persona | null) => void;
  setSubmittedMessage: (message: string) => void;
  refreshChatSessions: () => void;
  router: AppRouterInstance;
  pathname: string;
  searchParams: ReadonlyURLSearchParams | null;
  navigatingAway: React.MutableRefObject<boolean>;
  chatSessionIdRef: React.MutableRefObject<string | null>;
}

export interface PostProcessingParams {
  isNewSession: boolean;
  sessionId: string;
  finalMessage: BackendMessage | null;
  retrievalType: RetrievalType;
  searchParamBasedChatSessionName: string | null;
}

export class PostProcessor {
  constructor(private deps: PostProcessorDependencies) {}

  async processPostSubmission(params: PostProcessingParams): Promise<void> {
    const {
      isNewSession,
      sessionId,
      finalMessage,
      retrievalType,
      searchParamBasedChatSessionName,
    } = params;

    const {
      setAgenticGenerating,
      resetRegenerationState,
      updateChatState,
      setSelectedMessageForDocDisplay,
      setAlternativeGeneratingAssistant,
      setSubmittedMessage,
      refreshChatSessions,
      router,
      pathname,
      searchParams,
      navigatingAway,
      chatSessionIdRef,
    } = this.deps;

    console.log("Finished streaming");
    setAgenticGenerating(false);
    resetRegenerationState(sessionId);
    updateChatState("input");

    if (isNewSession) {
      console.log("Setting up new session");
      if (finalMessage) {
        setSelectedMessageForDocDisplay(finalMessage.message_id);
      }

      if (!searchParamBasedChatSessionName) {
        await new Promise((resolve) => setTimeout(resolve, 200));
        await nameChatSession(sessionId);
        refreshChatSessions();
      }

      // NOTE: don't switch pages if the user has navigated away from the chat
      if (
        sessionId === chatSessionIdRef.current ||
        chatSessionIdRef.current === null
      ) {
        const newUrl = buildChatUrl(searchParams, sessionId, null);
        // newUrl is like /chat?chatId=10
        // current page is like /chat

        if (pathname == "/chat" && !navigatingAway.current) {
          router.push(newUrl, { scroll: false });
        }
      }
    }

    if (
      finalMessage?.context_docs &&
      finalMessage.context_docs.top_documents.length > 0 &&
      retrievalType === RetrievalType.Search
    ) {
      setSelectedMessageForDocDisplay(finalMessage.message_id);
    }

    setAlternativeGeneratingAssistant(null);
    setSubmittedMessage("");
  }
}
