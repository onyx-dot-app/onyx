"use client";

import { redirect, useRouter, useSearchParams } from "next/navigation";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  personaIncludesRetrieval,
  useScrollonStream,
  getAvailableContextTokens,
} from "@/app/chat/services/lib";
import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { useFederatedConnectors, useFilters, useLlmManager } from "@/lib/hooks";
import { useFederatedOAuthStatus } from "@/lib/hooks/useFederatedOAuthStatus";
import { FeedbackType } from "@/app/chat/interfaces";
import { OnyxInitializingLoader } from "@/components/OnyxInitializingLoader";
import { FeedbackModal } from "@/app/chat/components/modal/FeedbackModal";
import { FiArrowDown } from "react-icons/fi";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Dropzone from "react-dropzone";
import ChatInputBar from "@/app/chat/components/input/ChatInputBar";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import { ChatPopup } from "@/app/chat/components/ChatPopup";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { useUser } from "@/components/user/UserProvider";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import { NoAssistantModal } from "@/components/modals/NoAssistantModal";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import TextView from "@/components/chat/TextView";
import { Modal } from "@/components/Modal";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import { getSourceMetadata } from "@/lib/sources";
import { SourceMetadata } from "@/lib/search/interfaces";
import { FederatedConnectorDetail, ValidSources } from "@/lib/types";
import { ChatSearchModal } from "@/app/chat/chat_search/ChatSearchModal";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { useScreenSize } from "@/hooks/useScreenSize";
import { DocumentResults } from "@/app/chat/components/documentSidebar/DocumentResults";
import { useChatController } from "@/app/chat/hooks/useChatController";
import { useAssistantController } from "@/app/chat/hooks/useAssistantController";
import { useChatSessionController } from "@/app/chat/hooks/useChatSessionController";
import { useDeepResearchToggle } from "@/app/chat/hooks/useDeepResearchToggle";
import {
  useChatSessionStore,
  useMaxTokens,
  useUncaughtError,
} from "@/app/chat/stores/useChatSessionStore";
import {
  useCurrentChatState,
  useSubmittedMessage,
  useLoadingError,
  useIsReady,
  useIsFetching,
  useCurrentMessageTree,
  useCurrentMessageHistory,
  useHasPerformedInitialScroll,
  useDocumentSidebarVisible,
  useHasSentLocalUserMessage,
} from "@/app/chat/stores/useChatSessionStore";
import { FederatedOAuthModal } from "@/components/chat/FederatedOAuthModal";
import { MessagesDisplay } from "@/app/chat/components/MessagesDisplay";
import WelcomeMessage from "@/app/chat/components/WelcomeMessage";
import ProjectContextPanel from "@/app/chat/components/projects/ProjectContextPanel";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import {
  getProjectTokenCount,
  getMaxSelectedDocumentTokens,
} from "@/app/chat/projects/projectsService";
import ProjectChatSessionList from "@/app/chat/components/projects/ProjectChatSessionList";
import { cn } from "@/lib/utils";
import { Suggestions } from "@/sections/Suggestions";

const DEFAULT_CONTEXT_TOKENS = 120_000;
interface ChatPageProps {
  documentSidebarInitialWidth?: number;
  firstMessage?: string;
}

export function ChatPage({
  documentSidebarInitialWidth,
  firstMessage,
}: ChatPageProps) {
  // Performance tracking
  // Keeping this here in case we need to track down slow renders in the future
  // const renderCount = useRef(0);
  // renderCount.current++;
  // const renderStartTime = performance.now();

  // useEffect(() => {
  //   const renderTime = performance.now() - renderStartTime;
  //   if (renderTime > 10) {
  //     console.log(
  //       `[ChatPage] Slow render #${renderCount.current}: ${renderTime.toFixed(
  //         2
  //       )}ms`
  //     );
  //   }
  // });

  const router = useRouter();
  const searchParams = useSearchParams();

  const {
    chatSessions,
    ccPairs,
    tags,
    documentSets,
    llmProviders,
    shouldShowWelcomeModal,
    refreshChatSessions,
  } = useChatContext();

  const {
    currentMessageFiles,
    setCurrentMessageFiles,
    currentProjectId,
    currentProjectDetails,
    lastFailedFiles,
    clearLastFailedFiles,
  } = useProjectsContext();

  const { height: screenHeight } = useScreenSize();

  // handle redirect if chat page is disabled
  // NOTE: this must be done here, in a client component since
  // settings are passed in via Context and therefore aren't
  // available in server-side components
  const settings = useContext(SettingsContext);
  const enterpriseSettings = settings?.enterpriseSettings;

  const isInitialLoad = useRef(true);

  const { agents: availableAssistants } = useAgentsContext();

  const [showApiKeyModal, setShowApiKeyModal] = useState(
    !shouldShowWelcomeModal
  );

  // Also fetch federated connectors for the sources list
  const { data: federatedConnectorsData } = useFederatedConnectors();
  const {
    connectors: federatedConnectorOAuthStatus,
    refetch: refetchFederatedConnectors,
  } = useFederatedOAuthStatus();

  const { user, isAdmin } = useUser();
  const existingChatIdRaw = searchParams?.get("chatId");

  const existingChatSessionId = existingChatIdRaw ? existingChatIdRaw : null;

  const selectedChatSession = chatSessions.find(
    (chatSession) => chatSession.id === existingChatSessionId
  );

  function processSearchParamsAndSubmitMessage(searchParamsString: string) {
    const newSearchParams = new URLSearchParams(searchParamsString);
    const message = newSearchParams?.get("user-prompt");

    filterManager.buildFiltersFromQueryString(
      newSearchParams.toString(),
      sources,
      documentSets.map((ds) => ds.name),
      tags
    );

    newSearchParams.delete(SEARCH_PARAM_NAMES.SEND_ON_LOAD);

    router.replace(`?${newSearchParams.toString()}`, { scroll: false });

    // If there's a message, submit it
    if (message) {
      onSubmit({
        message,
        currentMessageFiles,
        useAgentSearch: deepResearchEnabled,
      });
    }
  }

  const { selectedAssistant, setSelectedAssistantFromId, liveAssistant } =
    useAssistantController({
      selectedChatSession,
      onAssistantSelect: () => {
        // Only remove project context if user explicitly selected an assistant
        // (i.e., assistantId is present). Avoid clearing project when assistantId was removed.
        const newSearchParams = new URLSearchParams(
          searchParams?.toString() || ""
        );
        if (newSearchParams.has("assistantId")) {
          newSearchParams.delete("projectid");
          router.replace(`?${newSearchParams.toString()}`, { scroll: false });
        }
      },
    });

  const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({
    chatSessionId: existingChatSessionId,
    assistantId: selectedAssistant?.id,
  });

  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);

  const llmManager = useLlmManager(
    llmProviders,
    selectedChatSession,
    liveAssistant
  );

  const noAssistants = liveAssistant === null || liveAssistant === undefined;

  const availableSources: ValidSources[] = useMemo(() => {
    return ccPairs.map((ccPair) => ccPair.source);
  }, [ccPairs]);

  const sources: SourceMetadata[] = useMemo(() => {
    const uniqueSources = Array.from(new Set(availableSources));
    const regularSources = uniqueSources.map((source) =>
      getSourceMetadata(source)
    );

    // Add federated connectors as sources
    const federatedSources =
      federatedConnectorsData?.map((connector: FederatedConnectorDetail) => {
        return getSourceMetadata(connector.source);
      }) || [];

    // Combine sources and deduplicate based on internalName
    const allSources = [...regularSources, ...federatedSources];
    const deduplicatedSources = allSources.reduce((acc, source) => {
      const existing = acc.find((s) => s.internalName === source.internalName);
      if (!existing) {
        acc.push(source);
      }
      return acc;
    }, [] as SourceMetadata[]);

    return deduplicatedSources;
  }, [availableSources, federatedConnectorsData]);

  const { popup, setPopup } = usePopup();

  // Show popup if any files failed in ProjectsContext reconciliation
  useEffect(() => {
    if (lastFailedFiles && lastFailedFiles.length > 0) {
      const names = lastFailedFiles.map((f) => f.name).join(", ");
      setPopup({
        type: "error",
        message:
          lastFailedFiles.length === 1
            ? `File failed and was removed: ${names}`
            : `Files failed and were removed: ${names}`,
      });
      clearLastFailedFiles();
    }
  }, [lastFailedFiles, setPopup, clearLastFailedFiles]);

  const [message, setMessage] = useState(
    searchParams?.get(SEARCH_PARAM_NAMES.USER_PROMPT) || ""
  );

  const [projectPanelVisible, setProjectPanelVisible] = useState(true);

  const filterManager = useFilters();
  const [isChatSearchModalOpen, setIsChatSearchModalOpen] = useState(false);

  const [currentFeedback, setCurrentFeedback] = useState<
    [FeedbackType, number] | null
  >(null);

  const [aboveHorizon, setAboveHorizon] = useState(false);

  const scrollableDivRef = useRef<HTMLDivElement>(null);
  const lastMessageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLDivElement>(null);
  const endDivRef = useRef<HTMLDivElement>(null);
  const endPaddingRef = useRef<HTMLDivElement>(null);

  const scrollInitialized = useRef(false);

  const previousHeight = useRef<number>(
    inputRef.current?.getBoundingClientRect().height!
  );
  const scrollDist = useRef<number>(0);

  // Reset scroll state when switching chat sessions
  useEffect(() => {
    scrollDist.current = 0;
    setAboveHorizon(false);
  }, [existingChatSessionId]);

  function handleInputResize() {
    setTimeout(() => {
      if (
        inputRef.current &&
        lastMessageRef.current &&
        !waitForScrollRef.current
      ) {
        const newHeight: number =
          inputRef.current?.getBoundingClientRect().height!;
        const heightDifference = newHeight - previousHeight.current;
        if (
          previousHeight.current &&
          heightDifference != 0 &&
          endPaddingRef.current &&
          scrollableDivRef &&
          scrollableDivRef.current
        ) {
          endPaddingRef.current.style.transition = "height 0.3s ease-out";
          endPaddingRef.current.style.height = `${Math.max(
            newHeight - 50,
            0
          )}px`;

          if (autoScrollEnabled) {
            scrollableDivRef?.current.scrollBy({
              left: 0,
              top: Math.max(heightDifference, 0),
              behavior: "smooth",
            });
          }
        }
        previousHeight.current = newHeight;
      }
    }, 100);
  }

  const resetInputBar = useCallback(() => {
    setMessage("");
    setCurrentMessageFiles([]);
    if (endPaddingRef.current) {
      endPaddingRef.current.style.height = `95px`;
    }
  }, [setMessage, setCurrentMessageFiles]);

  const debounceNumber = 100; // time for debouncing

  // handle re-sizing of the text area
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    handleInputResize();
  }, [message]);

  // Add refs needed by useChatSessionController
  const chatSessionIdRef = useRef<string | null>(existingChatSessionId);
  const loadedIdSessionRef = useRef<string | null>(existingChatSessionId);
  const submitOnLoadPerformed = useRef<boolean>(false);

  // used for resizing of the document sidebar
  const masterFlexboxRef = useRef<HTMLDivElement>(null);
  const [maxDocumentSidebarWidth, setMaxDocumentSidebarWidth] = useState<
    number | null
  >(null);
  function adjustDocumentSidebarWidth() {
    if (masterFlexboxRef.current && document.documentElement.clientWidth) {
      // numbers below are based on the actual width the center section for different
      // screen sizes. `1700` corresponds to the custom "3xl" tailwind breakpoint
      // NOTE: some buffer is needed to account for scroll bars
      if (document.documentElement.clientWidth > 1700) {
        setMaxDocumentSidebarWidth(masterFlexboxRef.current.clientWidth - 950);
      } else if (document.documentElement.clientWidth > 1420) {
        setMaxDocumentSidebarWidth(masterFlexboxRef.current.clientWidth - 760);
      } else {
        setMaxDocumentSidebarWidth(masterFlexboxRef.current.clientWidth - 660);
      }
    }
  }

  function loadNewPageLogic(event: MessageEvent) {
    if (event.data.type === SUBMIT_MESSAGE_TYPES.PAGE_CHANGE) {
      try {
        const url = new URL(event.data.href);
        processSearchParamsAndSubmitMessage(url.searchParams.toString());
      } catch (error) {
        console.error("Error parsing URL:", error);
      }
    }
  }

  // Equivalent to `loadNewPageLogic`
  useEffect(() => {
    if (searchParams?.get(SEARCH_PARAM_NAMES.SEND_ON_LOAD)) {
      processSearchParamsAndSubmitMessage(searchParams.toString());
    }
  }, [searchParams, router]);

  useEffect(() => {
    adjustDocumentSidebarWidth();
    window.addEventListener("resize", adjustDocumentSidebarWidth);
    window.addEventListener("message", loadNewPageLogic);

    return () => {
      window.removeEventListener("message", loadNewPageLogic);
      window.removeEventListener("resize", adjustDocumentSidebarWidth);
    };
  }, []);

  if (!documentSidebarInitialWidth && maxDocumentSidebarWidth) {
    documentSidebarInitialWidth = Math.min(700, maxDocumentSidebarWidth);
  }

  const [selectedDocuments, setSelectedDocuments] = useState<OnyxDocument[]>(
    []
  );

  // Access chat state directly from the store
  const currentChatState = useCurrentChatState();
  const chatSessionId = useChatSessionStore((state) => state.currentSessionId);
  const submittedMessage = useSubmittedMessage();
  const loadingError = useLoadingError();
  const uncaughtError = useUncaughtError();
  const isReady = useIsReady();
  const maxTokens = useMaxTokens();
  const isFetchingChatMessages = useIsFetching();
  const completeMessageTree = useCurrentMessageTree();
  const messageHistory = useCurrentMessageHistory();
  const hasPerformedInitialScroll = useHasPerformedInitialScroll();
  const currentSessionHasSentLocalUserMessage = useHasSentLocalUserMessage();
  const documentSidebarVisible = useDocumentSidebarVisible();
  const updateHasPerformedInitialScroll = useChatSessionStore(
    (state) => state.updateHasPerformedInitialScroll
  );
  const updateCurrentDocumentSidebarVisible = useChatSessionStore(
    (state) => state.updateCurrentDocumentSidebarVisible
  );

  const clientScrollToBottom = useCallback(
    (fast?: boolean) => {
      waitForScrollRef.current = true;

      setTimeout(() => {
        if (!endDivRef.current || !scrollableDivRef.current) {
          console.error("endDivRef or scrollableDivRef not found");
          return;
        }

        const rect = endDivRef.current.getBoundingClientRect();
        const isVisible = rect.top >= 0 && rect.bottom <= window.innerHeight;

        if (isVisible) return;

        // Check if all messages are currently rendered
        // If all messages are already rendered, scroll immediately
        endDivRef.current.scrollIntoView({
          behavior: fast ? "auto" : "smooth",
        });

        if (chatSessionIdRef.current) {
          updateHasPerformedInitialScroll(chatSessionIdRef.current, true);
        }
      }, 50);

      // Reset waitForScrollRef after 1.5 seconds
      setTimeout(() => {
        waitForScrollRef.current = false;
      }, 1500);
    },
    [updateHasPerformedInitialScroll]
  );

  const { onSubmit, stopGenerating, handleMessageSpecificFileUpload } =
    useChatController({
      filterManager,
      llmManager,
      availableAssistants,
      liveAssistant,
      existingChatSessionId,
      selectedDocuments,
      searchParams,
      setPopup,
      clientScrollToBottom,
      resetInputBar,
      setSelectedAssistantFromId,
    });

  const { onMessageSelection, currentSessionFileTokenCount, projectFiles } =
    useChatSessionController({
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
    });

  const autoScrollEnabled = user?.preferences?.auto_scroll ?? false;

  useScrollonStream({
    chatState: currentChatState,
    scrollableDivRef,
    scrollDist,
    endDivRef,
    debounceNumber,
    mobile: settings?.isMobile,
    enableAutoScroll: autoScrollEnabled,
  });

  const getContainerHeight = useMemo(() => {
    return () => {
      if (!currentSessionHasSentLocalUserMessage) {
        return undefined;
      }
      if (autoScrollEnabled) return undefined;

      if (screenHeight < 600) return "40vh";
      if (screenHeight < 1200) return "50vh";
      return "60vh";
    };
  }, [autoScrollEnabled, screenHeight, currentSessionHasSentLocalUserMessage]);

  const waitForScrollRef = useRef(false);

  useSendMessageToParent();

  const retrievalEnabled = useMemo(() => {
    if (liveAssistant) {
      return liveAssistant.tools.some(
        (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID
      );
    }
    return false;
  }, [liveAssistant]);

  useEffect(() => {
    if (
      (!personaIncludesRetrieval &&
        (!selectedDocuments || selectedDocuments.length === 0) &&
        documentSidebarVisible) ||
      chatSessionId == undefined
    ) {
      updateCurrentDocumentSidebarVisible(false);
    }
    clientScrollToBottom();
  }, [chatSessionId]);

  const [stackTraceModalContent, setStackTraceModalContent] = useState<
    string | null
  >(null);

  const HORIZON_DISTANCE = 800;
  const handleScroll = useCallback(() => {
    const scrollDistance =
      endDivRef?.current?.getBoundingClientRect()?.top! -
      inputRef?.current?.getBoundingClientRect()?.top!;
    scrollDist.current = scrollDistance;
    setAboveHorizon(scrollDist.current > HORIZON_DISTANCE);
  }, []);

  function handleResubmitLastMessage() {
    // Grab the last user-type message
    const lastUserMsg = messageHistory
      .slice()
      .reverse()
      .find((m) => m.type === "user");
    if (!lastUserMsg) {
      setPopup({
        message: "No previously-submitted user message found.",
        type: "error",
      });
      return;
    }

    // We call onSubmit, passing a `messageOverride`
    onSubmit({
      message: lastUserMsg.message,
      currentMessageFiles: currentMessageFiles,
      useAgentSearch: deepResearchEnabled,
      messageIdToResend: lastUserMsg.messageId,
    });
  }

  const toggleDocumentSidebar = useCallback(() => {
    if (!documentSidebarVisible) {
      updateCurrentDocumentSidebarVisible(true);
    } else {
      updateCurrentDocumentSidebarVisible(false);
    }
  }, [documentSidebarVisible, updateCurrentDocumentSidebarVisible]);

  const toggleChatSessionSearchModal = useCallback(
    () => setIsChatSearchModalOpen((open) => !open),
    [setIsChatSearchModalOpen]
  );

  if (!user) {
    redirect("/auth/login");
  }

  const toggleDocumentSelection = useCallback((document: OnyxDocument) => {
    setSelectedDocuments((prev) =>
      prev.some((d) => d.document_id === document.document_id)
        ? prev.filter((d) => d.document_id !== document.document_id)
        : [...prev, document]
    );
  }, []);

  const handleShowApiKeyModal = useCallback(() => {
    setShowApiKeyModal(true);
  }, []);

  const handleChatInputSubmit = useCallback(() => {
    onSubmit({
      message: message,
      currentMessageFiles: currentMessageFiles,
      useAgentSearch: deepResearchEnabled,
    });
  }, [message, onSubmit, currentMessageFiles, deepResearchEnabled]);

  // Memoized callbacks for DocumentResults
  const handleMobileDocumentSidebarClose = useCallback(() => {
    updateCurrentDocumentSidebarVisible(false);
  }, [updateCurrentDocumentSidebarVisible]);

  const handleDesktopDocumentSidebarClose = useCallback(() => {
    setTimeout(() => updateCurrentDocumentSidebarVisible(false), 300);
  }, [updateCurrentDocumentSidebarVisible]);

  // Determine whether to show the centered input (no messages yet)
  const showCenteredInput =
    messageHistory.length === 0 &&
    !isFetchingChatMessages &&
    !loadingError &&
    !submittedMessage;

  // Only show the centered hero layout when there is NO project selected
  // and there are no messages yet. If a project is selected, prefer a top layout.
  const showCenteredHero = currentProjectId === null && showCenteredInput;

  useEffect(() => {
    if (currentProjectId !== null && showCenteredInput) {
      setProjectPanelVisible(true);
    }
    if (!showCenteredInput) {
      setProjectPanelVisible(false);
    }
  }, [currentProjectId, showCenteredInput]);

  // When no chat session exists but a project is selected, fetch the
  // total tokens for the project's files so upload UX can compare
  // against available context similar to session-based flows.
  const [projectContextTokenCount, setProjectContextTokenCount] = useState(0);
  // Fetch project-level token count when no chat session exists.
  // Note: useEffect cannot be async, so we define an inner async function (run)
  // and invoke it. The `cancelled` guard prevents setting state after the
  // component unmounts or when the dependencies change and a newer effect run
  // supersedes an older in-flight request.
  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!existingChatSessionId && currentProjectId !== null) {
        try {
          const total = await getProjectTokenCount(currentProjectId);
          if (!cancelled) setProjectContextTokenCount(total || 0);
        } catch {
          if (!cancelled) setProjectContextTokenCount(0);
        }
      } else {
        setProjectContextTokenCount(0);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [existingChatSessionId, currentProjectId, currentProjectDetails?.files]);

  // Available context tokens source of truth:
  // - If a chat session exists, fetch from session API (dynamic per session/model)
  // - If no session, derive from the default/current persona's max document tokens
  const [availableContextTokens, setAvailableContextTokens] = useState<number>(
    DEFAULT_CONTEXT_TOKENS * 0.5
  );
  useEffect(() => {
    let cancelled = false;
    async function run() {
      try {
        if (existingChatSessionId) {
          const available = await getAvailableContextTokens(
            existingChatSessionId
          );
          const capped_context_tokens =
            (available ?? DEFAULT_CONTEXT_TOKENS) * 0.5;
          if (!cancelled) setAvailableContextTokens(capped_context_tokens);
        } else {
          const personaId = (selectedAssistant || liveAssistant)?.id;
          if (personaId !== undefined && personaId !== null) {
            const maxTokens = await getMaxSelectedDocumentTokens(personaId);
            const capped_context_tokens =
              (maxTokens ?? DEFAULT_CONTEXT_TOKENS) * 0.5;
            if (!cancelled) setAvailableContextTokens(capped_context_tokens);
          } else if (!cancelled) {
            setAvailableContextTokens(DEFAULT_CONTEXT_TOKENS * 0.5);
          }
        }
      } catch (e) {
        if (!cancelled) setAvailableContextTokens(DEFAULT_CONTEXT_TOKENS * 0.5);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [existingChatSessionId, selectedAssistant?.id, liveAssistant?.id]);

  // handle error case where no assistants are available
  if (noAssistants) {
    return (
      <>
        <HealthCheckBanner />
        <NoAssistantModal isAdmin={isAdmin} />
      </>
    );
  }

  if (!isReady) return <OnyxInitializingLoader />;

  return (
    <>
      <HealthCheckBanner />

      {showApiKeyModal && !shouldShowWelcomeModal && (
        <ApiKeyModal
          hide={() => setShowApiKeyModal(false)}
          setPopup={setPopup}
        />
      )}

      {/* ChatPopup is a custom popup that displays a admin-specified message on initial user visit. 
      Only used in the EE version of the app. */}
      {popup}

      <ChatPopup />

      <FeedbackModal setPopup={setPopup} />

      <ChatSearchModal
        open={isChatSearchModalOpen}
        onCloseModal={() => setIsChatSearchModalOpen(false)}
      />

      {retrievalEnabled && documentSidebarVisible && settings?.isMobile && (
        <div className="md:hidden">
          <Modal
            hideDividerForTitle
            onOutsideClick={() => updateCurrentDocumentSidebarVisible(false)}
            title="Sources"
          >
            {/* IMPORTANT: this is a memoized component, and it's very important
            for performance reasons that this stays true. MAKE SURE that all function 
            props are wrapped in useCallback. */}
            <DocumentResults
              setPresentingDocument={setPresentingDocument}
              modal={true}
              closeSidebar={handleMobileDocumentSidebarClose}
              selectedDocuments={selectedDocuments}
              toggleDocumentSelection={toggleDocumentSelection}
              clearSelectedDocuments={() => setSelectedDocuments([])}
              // TODO (chris): fix
              selectedDocumentTokens={0}
              maxTokens={maxTokens}
            />
          </Modal>
        </div>
      )}

      {presentingDocument && (
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}

      {stackTraceModalContent && (
        <ExceptionTraceModal
          onOutsideClick={() => setStackTraceModalContent(null)}
          exceptionTrace={stackTraceModalContent}
        />
      )}

      <FederatedOAuthModal />

      <div className="flex flex-row h-full w-full">
        <div
          ref={masterFlexboxRef}
          className="flex h-full w-full overflow-x-hidden"
        >
          {documentSidebarInitialWidth !== undefined && (
            <Dropzone
              key={chatSessionId}
              onDrop={(acceptedFiles) =>
                handleMessageSpecificFileUpload(acceptedFiles)
              }
              noClick
            >
              {({ getRootProps }) => (
                <div
                  className="h-full w-full relative flex-auto min-w-0"
                  {...getRootProps()}
                >
                  <div
                    onScroll={handleScroll}
                    className="w-full h-[calc(100dvh-100px)] flex flex-col default-scrollbar overflow-y-auto overflow-x-hidden relative"
                    ref={scrollableDivRef}
                  >
                    <MessagesDisplay
                      messageHistory={messageHistory}
                      completeMessageTree={completeMessageTree}
                      liveAssistant={liveAssistant}
                      llmManager={llmManager}
                      deepResearchEnabled={deepResearchEnabled}
                      currentMessageFiles={currentMessageFiles}
                      setPresentingDocument={setPresentingDocument}
                      setCurrentFeedback={setCurrentFeedback}
                      onSubmit={onSubmit}
                      onMessageSelection={onMessageSelection}
                      stopGenerating={stopGenerating}
                      uncaughtError={uncaughtError}
                      loadingError={loadingError}
                      handleResubmitLastMessage={handleResubmitLastMessage}
                      autoScrollEnabled={autoScrollEnabled}
                      getContainerHeight={getContainerHeight}
                      lastMessageRef={lastMessageRef}
                      endPaddingRef={endPaddingRef}
                      endDivRef={endDivRef}
                      hasPerformedInitialScroll={hasPerformedInitialScroll}
                      chatSessionId={chatSessionId}
                      enterpriseSettings={enterpriseSettings}
                    />
                  </div>

                  <div
                    ref={inputRef}
                    className={cn(
                      "absolute pointer-events-none z-10 w-full",
                      showCenteredHero
                        ? "inset-0"
                        : currentProjectId !== null && showCenteredInput
                          ? "top-0 left-0 right-0"
                          : "bottom-0 left-0 right-0 translate-y-0"
                    )}
                  >
                    {!showCenteredInput && aboveHorizon && (
                      <div className="mx-auto w-fit !pointer-events-none flex sticky justify-center">
                        <button
                          onClick={() => clientScrollToBottom()}
                          className="p-1 pointer-events-auto text-text-03 rounded-2xl bg-background-neutral-02 border border-border mx-auto"
                        >
                          <FiArrowDown size={18} />
                        </button>
                      </div>
                    )}

                    <div
                      className={cn(
                        "pointer-events-auto w-[95%] mx-auto relative text-text-04 justify-center",
                        showCenteredHero
                          ? "h-full grid grid-rows-[0.85fr_auto_1.15fr]"
                          : "mb-8"
                      )}
                    >
                      {currentProjectId == null && showCenteredInput && (
                        <WelcomeMessage />
                      )}
                      <div
                        className={cn(
                          "flex flex-col items-center justify-center",
                          showCenteredHero && "row-start-2"
                        )}
                      >
                        {currentProjectId !== null && projectPanelVisible && (
                          <ProjectContextPanel
                            projectTokenCount={projectContextTokenCount}
                            availableContextTokens={availableContextTokens}
                            setPresentingDocument={setPresentingDocument}
                          />
                        )}
                        <ChatInputBar
                          deepResearchEnabled={deepResearchEnabled}
                          toggleDeepResearch={toggleDeepResearch}
                          toggleDocumentSidebar={toggleDocumentSidebar}
                          filterManager={filterManager}
                          llmManager={llmManager}
                          removeDocs={() => setSelectedDocuments([])}
                          retrievalEnabled={retrievalEnabled}
                          showConfigureAPIKey={handleShowApiKeyModal}
                          selectedDocuments={selectedDocuments}
                          message={message}
                          setMessage={setMessage}
                          stopGenerating={stopGenerating}
                          onSubmit={handleChatInputSubmit}
                          chatState={currentChatState}
                          currentSessionFileTokenCount={
                            existingChatSessionId
                              ? currentSessionFileTokenCount
                              : projectContextTokenCount
                          }
                          availableContextTokens={availableContextTokens}
                          selectedAssistant={selectedAssistant || liveAssistant}
                          handleFileUpload={handleMessageSpecificFileUpload}
                          textAreaRef={textAreaRef}
                          setPresentingDocument={setPresentingDocument}
                        />
                      </div>

                      {currentProjectId !== null && (
                        <div className="transition-all duration-700 ease-out">
                          <ProjectChatSessionList />
                        </div>
                      )}

                      {liveAssistant.starter_messages &&
                        liveAssistant.starter_messages.length > 0 &&
                        messageHistory.length === 0 &&
                        showCenteredHero && (
                          <div className="mt-6 row-start-3 max-w-[50rem]">
                            <Suggestions onSubmit={onSubmit} />
                          </div>
                        )}
                      {enterpriseSettings &&
                        enterpriseSettings.custom_lower_disclaimer_content && (
                          <div className="mobile:hidden mt-4 flex items-center justify-center relative w-[95%] mx-auto">
                            <div className="text-sm text-text-500 max-w-searchbar-max px-4 text-center">
                              <MinimalMarkdown
                                content={
                                  enterpriseSettings.custom_lower_disclaimer_content
                                }
                              />
                            </div>
                          </div>
                        )}
                      {enterpriseSettings &&
                        enterpriseSettings.use_custom_logotype && (
                          <div className="hidden lg:block absolute right-0 bottom-0">
                            <img
                              src="/api/enterprise-settings/logotype"
                              alt="logotype"
                              style={{ objectFit: "contain" }}
                              className="w-fit h-8"
                            />
                          </div>
                        )}
                    </div>
                  </div>
                </div>
              )}
            </Dropzone>
          )}
        </div>

        <div
          className={cn(
            "flex-shrink-0 overflow-hidden transition-all duration-300 ease-in-out",
            documentSidebarVisible && !settings?.isMobile
              ? "w-[25rem]"
              : "w-[0rem]"
          )}
        >
          <div className="h-full w-[25rem]">
            {/* IMPORTANT: this is a memoized component, and it's very important
              for performance reasons that this stays true. MAKE SURE that all function
              props are wrapped in useCallback. */}
            <DocumentResults
              setPresentingDocument={setPresentingDocument}
              modal={false}
              closeSidebar={handleDesktopDocumentSidebarClose}
              selectedDocuments={selectedDocuments}
              toggleDocumentSelection={toggleDocumentSelection}
              clearSelectedDocuments={() => setSelectedDocuments([])}
              // TODO (chris): fix
              selectedDocumentTokens={0}
              maxTokens={maxTokens}
            />
          </div>
        </div>
      </div>
    </>
  );
}
