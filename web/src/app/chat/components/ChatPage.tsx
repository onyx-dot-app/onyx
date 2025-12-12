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
import { OnyxInitializingLoader } from "@/components/OnyxInitializingLoader";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Dropzone from "react-dropzone";
import ChatInputBar from "@/app/chat/components/input/ChatInputBar";
import { useChatSessions } from "@/lib/hooks/useChatSessions";
import { useCCPairs } from "@/lib/hooks/useCCPairs";
import { useTags } from "@/lib/hooks/useTags";
import { useDocumentSets } from "@/lib/hooks/useDocumentSets";
import { useAgents } from "@/lib/hooks/useAgents";
import { ChatPopup } from "@/app/chat/components/ChatPopup";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { useUser } from "@/components/user/UserProvider";
import NoAssistantModal from "@/components/modals/NoAssistantModal";
import TextView from "@/components/chat/TextView";
import Modal from "@/refresh-components/Modal";
import SvgFileText from "@/icons/file-text";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import { getSourceMetadata } from "@/lib/sources";
import { SourceMetadata } from "@/lib/search/interfaces";
import { FederatedConnectorDetail, UserRole, ValidSources } from "@/lib/types";
import useScreenSize from "@/hooks/useScreenSize";
import { DocumentResults } from "@/app/chat/components/documentSidebar/DocumentResults";
import { useChatController } from "@/app/chat/hooks/useChatController";
import { useAssistantController } from "@/app/chat/hooks/useAssistantController";
import { useChatSessionController } from "@/app/chat/hooks/useChatSessionController";
import { useDeepResearchToggle } from "@/app/chat/hooks/useDeepResearchToggle";
import { useIsDefaultAgent } from "@/app/chat/hooks/useIsDefaultAgent";
import {
  useChatSessionStore,
  useMaxTokens,
  useChatPageLayout,
  useUncaughtError,
} from "@/app/chat/stores/useChatSessionStore";
import {
  useCurrentChatState,
  useIsReady,
  useCurrentMessageTree,
  useHasPerformedInitialScroll,
  useDocumentSidebarVisible,
  useHasSentLocalUserMessage,
} from "@/app/chat/stores/useChatSessionStore";
import FederatedOAuthModal from "@/components/chat/FederatedOAuthModal";
import MessagesDisplay from "@/app/chat/components/MessagesDisplay";
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
import OnboardingFlow from "@/refresh-components/onboarding/OnboardingFlow";
import { useOnboardingState } from "@/refresh-components/onboarding/useOnboardingState";
import { OnboardingStep } from "@/refresh-components/onboarding/types";
import AppPageLayout from "@/layouts/AppPageLayout";
import { HeaderData } from "@/lib/headers/fetchHeaderDataSS";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgChevronDown from "@/icons/chevron-down";

const DEFAULT_CONTEXT_TOKENS = 120_000;

interface ChatPageProps {
  documentSidebarInitialWidth?: number;
  firstMessage?: string;
  headerData: HeaderData;
}

export default function ChatPage({
  documentSidebarInitialWidth,
  firstMessage,
  headerData,
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

  // Use SWR hooks for data fetching
  const { chatSessions, refreshChatSessions } = useChatSessions();
  const { ccPairs } = useCCPairs();
  const { tags } = useTags();
  const { documentSets } = useDocumentSets();

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

  const { agents: availableAssistants, isLoading: isLoadingAgents } =
    useAgents();

  // Also fetch federated connectors for the sources list
  const { data: federatedConnectorsData } = useFederatedConnectors();

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
  const [showOnboarding, setShowOnboarding] = useState(false);

  // Initialize onboarding state
  const {
    state: onboardingState,
    actions: onboardingActions,
    llmDescriptors,
    isLoading: isLoadingOnboarding,
  } = useOnboardingState(liveAssistant);

  const llmManager = useLlmManager(selectedChatSession, liveAssistant);

  // On first render, open onboarding if there are no configured LLM providers.
  // Wait until providers have loaded before making this decision.
  const hasCheckedOnboarding = useRef(false);
  useEffect(() => {
    // Only check once, and only after data has loaded
    if (hasCheckedOnboarding.current || llmManager.isLoadingProviders) {
      return;
    }
    hasCheckedOnboarding.current = true;
    setShowOnboarding(llmManager.hasAnyProvider === false);
  }, [llmManager.isLoadingProviders, llmManager.hasAnyProvider]);

  const noAssistants = liveAssistant === null || liveAssistant === undefined;

  const availableSources: ValidSources[] = useMemo(() => {
    return (ccPairs ?? []).map((ccPair) => ccPair.source);
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

  const isDefaultAgent = useIsDefaultAgent({
    liveAssistant,
    existingChatSessionId,
    selectedChatSession,
    settings,
  });

  const [aboveHorizon, setAboveHorizon] = useState(false);

  const scrollableDivRef = useRef<HTMLDivElement>(null);
  const lastMessageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLDivElement>(null);
  const endDivRef = useRef<HTMLDivElement>(null);

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
          scrollableDivRef &&
          scrollableDivRef.current
        ) {
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
    window.addEventListener("message", loadNewPageLogic);

    return () => {
      window.removeEventListener("message", loadNewPageLogic);
    };
  }, []);

  const [selectedDocuments, setSelectedDocuments] = useState<OnyxDocument[]>(
    []
  );

  // Access chat state directly from the store
  const currentChatState = useCurrentChatState();
  const chatSessionId = useChatSessionStore((state) => state.currentSessionId);
  const uncaughtError = useUncaughtError();
  const isReady = useIsReady();
  const completeMessageTree = useCurrentMessageTree();
  const hasPerformedInitialScroll = useHasPerformedInitialScroll();
  const currentSessionHasSentLocalUserMessage = useHasSentLocalUserMessage();
  const documentSidebarVisible = useDocumentSidebarVisible();
  const updateHasPerformedInitialScroll = useChatSessionStore(
    (state) => state.updateHasPerformedInitialScroll
  );
  const updateCurrentDocumentSidebarVisible = useChatSessionStore(
    (state) => state.updateCurrentDocumentSidebarVisible
  );
  const {
    showCenteredInput: showCenteredInputRaw,
    loadingError,
    messageHistory,
  } = useChatPageLayout();

  // When loading an existing chat session, always show input at bottom
  // to prevent layout shift from centered → bottom position
  const showCenteredInput = existingChatSessionId
    ? false
    : showCenteredInputRaw;

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

  const handleChatInputSubmit = useCallback(() => {
    onSubmit({
      message: message,
      currentMessageFiles: currentMessageFiles,
      useAgentSearch: deepResearchEnabled,
    });
    setShowOnboarding(false);
  }, [message, onSubmit, currentMessageFiles, deepResearchEnabled]);

  // Memoized callbacks for DocumentResults
  const handleMobileDocumentSidebarClose = useCallback(() => {
    updateCurrentDocumentSidebarVisible(false);
  }, [updateCurrentDocumentSidebarVisible]);

  const handleDesktopDocumentSidebarClose = useCallback(() => {
    setTimeout(() => updateCurrentDocumentSidebarVisible(false), 300);
  }, [updateCurrentDocumentSidebarVisible]);

  const desktopDocumentSidebar =
    retrievalEnabled && !settings?.isMobile ? (
      <div
        className={cn(
          "flex-shrink-0 overflow-hidden transition-all duration-300 ease-in-out",
          documentSidebarVisible ? "w-[25rem]" : "w-[0rem]"
        )}
      >
        <div className="h-full w-[25rem]">
          <DocumentResults
            setPresentingDocument={setPresentingDocument}
            modal={false}
            closeSidebar={handleDesktopDocumentSidebarClose}
            selectedDocuments={selectedDocuments}
          />
        </div>
      </div>
    ) : null;

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
  // Only show this after agents have loaded to prevent flash during initial load
  if (noAssistants && !isLoadingAgents) {
    return (
      <>
        <HealthCheckBanner />
        <NoAssistantModal />
      </>
    );
  }

  if (!isReady) return <OnyxInitializingLoader />;

  return (
    <>
      <HealthCheckBanner />

      {/* ChatPopup is a custom popup that displays a admin-specified message on initial user visit.
      Only used in the EE version of the app. */}
      {popup}

      <ChatPopup />

      {retrievalEnabled && documentSidebarVisible && settings?.isMobile && (
        <div className="md:hidden">
          <Modal
            open
            onOpenChange={() => updateCurrentDocumentSidebarVisible(false)}
          >
            <Modal.Content medium>
              <Modal.Header
                icon={SvgFileText}
                title="Sources"
                onClose={() => updateCurrentDocumentSidebarVisible(false)}
              />
              <Modal.Body>
                {/* IMPORTANT: this is a memoized component, and it's very important
                for performance reasons that this stays true. MAKE SURE that all function
                props are wrapped in useCallback. */}
                <DocumentResults
                  setPresentingDocument={setPresentingDocument}
                  modal={true}
                  closeSidebar={handleMobileDocumentSidebarClose}
                  selectedDocuments={selectedDocuments}
                />
              </Modal.Body>
            </Modal.Content>
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

      <div className="flex h-full w-full flex-row-reverse">
        {desktopDocumentSidebar}

        <AppPageLayout
          settings={headerData.settings}
          chatSession={headerData.chatSession}
        >
          <Dropzone
            onDrop={(acceptedFiles) =>
              handleMessageSpecificFileUpload(acceptedFiles)
            }
            noClick
          >
            {({ getRootProps }) => (
              <div className="h-full w-full flex flex-col" {...getRootProps()}>
                {/*{!showCenteredInput && aboveHorizon && (
                  <div className="mx-auto flex justify-center py-4">
                    <IconButton
                      icon={SvgChevronDown}
                      onClick={() => clientScrollToBottom()}
                    />
                  </div>
                )}*/}

                <div
                  ref={scrollableDivRef}
                  onScroll={handleScroll}
                  className="w-full flex-1 flex flex-col default-scrollbar overflow-y-auto overflow-x-hidden relative"
                >
                  <MessagesDisplay
                    messageHistory={messageHistory}
                    completeMessageTree={completeMessageTree}
                    liveAssistant={liveAssistant}
                    llmManager={llmManager}
                    deepResearchEnabled={deepResearchEnabled}
                    currentMessageFiles={currentMessageFiles}
                    setPresentingDocument={setPresentingDocument}
                    onSubmit={onSubmit}
                    onMessageSelection={onMessageSelection}
                    stopGenerating={stopGenerating}
                    uncaughtError={uncaughtError}
                    loadingError={loadingError}
                    handleResubmitLastMessage={handleResubmitLastMessage}
                    autoScrollEnabled={autoScrollEnabled}
                    getContainerHeight={getContainerHeight}
                    lastMessageRef={lastMessageRef}
                    endDivRef={endDivRef}
                    hasPerformedInitialScroll={hasPerformedInitialScroll}
                    chatSessionId={chatSessionId}
                    enterpriseSettings={enterpriseSettings}
                  />
                </div>

                <div ref={inputRef} className="w-full">
                  <div
                    className={cn(
                      "pointer-events-auto w-[95%] mx-auto relative text-text-04 justify-center",
                      showCenteredHero
                        ? "h-full grid grid-rows-[1fr_auto_1fr]"
                        : "mb-8"
                    )}
                  >
                    {currentProjectId == null && showCenteredInput && (
                      <WelcomeMessage
                        agent={liveAssistant}
                        isDefaultAgent={isDefaultAgent}
                      />
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

                      {(showOnboarding ||
                        (user?.role !== UserRole.ADMIN &&
                          !user?.personalization?.name)) &&
                        currentProjectId === null && (
                          <OnboardingFlow
                            handleHideOnboarding={() =>
                              setShowOnboarding(false)
                            }
                            state={onboardingState}
                            actions={onboardingActions}
                            llmDescriptors={llmDescriptors}
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
                        disabled={
                          (!llmManager.isLoadingProviders &&
                            llmManager.hasAnyProvider === false) ||
                          (!isLoadingOnboarding &&
                            onboardingState.currentStep !==
                              OnboardingStep.Complete)
                        }
                      />
                    </div>

                    {currentProjectId !== null && (
                      <div className="transition-all duration-700 ease-out">
                        <ProjectChatSessionList />
                      </div>
                    )}

                    {liveAssistant?.starter_messages &&
                      liveAssistant.starter_messages.length > 0 &&
                      messageHistory.length === 0 &&
                      showCenteredHero && (
                        <div className="mt-6 row-start-3 max-w-[50rem]">
                          <Suggestions onSubmit={onSubmit} />
                        </div>
                      )}
                  </div>
                </div>
              </div>
            )}
          </Dropzone>
        </AppPageLayout>
      </div>
    </>
  );
}
