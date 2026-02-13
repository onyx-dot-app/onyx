"use client";

import { redirect, useRouter, useSearchParams } from "next/navigation";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  personaIncludesRetrieval,
  getAvailableContextTokens,
} from "@/app/app/services/lib";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "@/hooks/useToast";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { useFederatedConnectors, useFilters, useLlmManager } from "@/lib/hooks";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import OnyxInitializingLoader from "@/components/OnyxInitializingLoader";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { useSettingsContext } from "@/providers/SettingsProvider";
import Dropzone from "react-dropzone";
import AppInputBar, { AppInputBarHandle } from "@/sections/input/AppInputBar";
import useChatSessions from "@/hooks/useChatSessions";
import useCCPairs from "@/hooks/useCCPairs";
import useTags from "@/hooks/useTags";
import { useDocumentSets } from "@/lib/hooks/useDocumentSets";
import { useAgents } from "@/hooks/useAgents";
import { AppPopup } from "@/app/app/components/AppPopup";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";
import { useUser } from "@/providers/UserProvider";
import NoAssistantModal from "@/components/modals/NoAssistantModal";
import TextViewModal from "@/sections/modals/TextViewModal";
import Modal from "@/refresh-components/Modal";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import { getSourceMetadata } from "@/lib/sources";
import { SourceMetadata } from "@/lib/search/interfaces";
import { FederatedConnectorDetail, UserRole, ValidSources } from "@/lib/types";
import DocumentsSidebar from "@/sections/document-sidebar/DocumentsSidebar";
import useChatController from "@/hooks/useChatController";
import useAgentController from "@/hooks/useAgentController";
import useChatSessionController from "@/hooks/useChatSessionController";
import useDeepResearchToggle from "@/hooks/useDeepResearchToggle";
import useIsDefaultAgent from "@/hooks/useIsDefaultAgent";
import {
  useChatSessionStore,
  useCurrentMessageHistory,
} from "@/app/app/stores/useChatSessionStore";
import {
  useCurrentChatState,
  useIsReady,
  useDocumentSidebarVisible,
} from "@/app/app/stores/useChatSessionStore";
import FederatedOAuthModal from "@/components/chat/FederatedOAuthModal";
import ChatScrollContainer, {
  ChatScrollContainerHandle,
} from "@/sections/chat/ChatScrollContainer";
import ProjectContextPanel from "@/app/app/components/projects/ProjectContextPanel";
import { useProjectsContext } from "@/providers/ProjectsContext";
import {
  getProjectTokenCount,
  getMaxSelectedDocumentTokens,
} from "@/app/app/projects/projectsService";
import ProjectChatSessionList from "@/app/app/components/projects/ProjectChatSessionList";
import { cn } from "@/lib/utils";
import Suggestions from "@/sections/Suggestions";
import OnboardingFlow from "@/refresh-components/onboarding/OnboardingFlow";
import { OnboardingStep } from "@/refresh-components/onboarding/types";
import { useShowOnboarding } from "@/hooks/useShowOnboarding";
import * as AppLayouts from "@/layouts/app-layouts";
import { SvgChevronDown, SvgFileText } from "@opal/icons";
import { Button } from "@opal/components";
import Spacer from "@/refresh-components/Spacer";
import { DEFAULT_CONTEXT_TOKENS } from "@/lib/constants";
import useAppFocus from "@/hooks/useAppFocus";
import { useQueryController } from "@/providers/QueryControllerProvider";
import WelcomeMessage from "@/app/app/components/WelcomeMessage";
import ChatUI from "@/sections/chat/ChatUI";
import { eeGated } from "@/ce";
import EESearchUI from "@/ee/sections/SearchUI";
const SearchUI = eeGated(EESearchUI);
import { motion, AnimatePresence } from "motion/react";
import { useAppMode } from "@/providers/AppModeProvider";

interface FadeProps {
  show: boolean;
  children?: React.ReactNode;
  className?: string;
}

function Fade({ show, children, className }: FadeProps) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className={className}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export interface ChatPageProps {
  firstMessage?: string;
}

export default function AppPage({ firstMessage }: ChatPageProps) {
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
  const appFocus = useAppFocus();
  const { setAppMode } = useAppMode();
  const searchParams = useSearchParams();

  // Use SWR hooks for data fetching
  const {
    chatSessions,
    refreshChatSessions,
    currentChatSession,
    currentChatSessionId,
    isLoading: isLoadingChatSessions,
  } = useChatSessions();
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

  // When changing from project chat to main chat (or vice-versa), clear forced tools
  const { setForcedToolIds } = useForcedTools();
  useEffect(() => {
    setForcedToolIds([]);
  }, [currentProjectId, setForcedToolIds]);

  // handle redirect if chat page is disabled
  // NOTE: this must be done here, in a client component since
  // settings are passed in via Context and therefore aren't
  // available in server-side components
  const settings = useSettingsContext();

  const isInitialLoad = useRef(true);

  const { agents, isLoading: isLoadingAgents } = useAgents();

  // Also fetch federated connectors for the sources list
  const { data: federatedConnectorsData } = useFederatedConnectors();

  const { user } = useUser();

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
        deepResearch: deepResearchEnabled,
      });
    }
  }

  const { selectedAssistant, setSelectedAssistantFromId, liveAssistant } =
    useAgentController({
      selectedChatSession: currentChatSession,
      onAssistantSelect: () => {
        // Only remove project context if user explicitly selected an assistant
        // (i.e., assistantId is present). Avoid clearing project when assistantId was removed.
        const newSearchParams = new URLSearchParams(
          searchParams?.toString() || ""
        );
        if (newSearchParams.has(SEARCH_PARAM_NAMES.PERSONA_ID)) {
          newSearchParams.delete(SEARCH_PARAM_NAMES.PROJECT_ID);
          router.replace(`?${newSearchParams.toString()}`, { scroll: false });
        }
      },
    });

  const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({
    chatSessionId: currentChatSessionId,
    assistantId: selectedAssistant?.id,
  });

  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);

  const llmManager = useLlmManager(
    currentChatSession ?? undefined,
    liveAssistant
  );

  const {
    showOnboarding,
    onboardingState,
    onboardingActions,
    llmDescriptors,
    isLoadingOnboarding,
    finishOnboarding,
    hideOnboarding,
  } = useShowOnboarding({
    liveAssistant,
    isLoadingProviders: llmManager.isLoadingProviders,
    hasAnyProvider: llmManager.hasAnyProvider,
    isLoadingChatSessions,
    chatSessionsCount: chatSessions.length,
    userId: user?.id,
  });

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

  // Show toast if any files failed in ProjectsContext reconciliation
  useEffect(() => {
    if (lastFailedFiles && lastFailedFiles.length > 0) {
      const names = lastFailedFiles.map((f) => f.name).join(", ");
      toast.error(
        lastFailedFiles.length === 1
          ? `File failed and was removed: ${names}`
          : `Files failed and were removed: ${names}`
      );
      clearLastFailedFiles();
    }
  }, [lastFailedFiles, clearLastFailedFiles]);

  const chatInputBarRef = useRef<AppInputBarHandle>(null);

  const filterManager = useFilters();

  const isDefaultAgent = useIsDefaultAgent({
    liveAssistant,
    existingChatSessionId: currentChatSessionId,
    selectedChatSession: currentChatSession ?? undefined,
    settings,
  });

  const scrollContainerRef = useRef<ChatScrollContainerHandle>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);

  // Reset scroll button when session changes
  useEffect(() => {
    setShowScrollButton(false);
  }, [currentChatSessionId]);

  const handleScrollToBottom = useCallback(() => {
    scrollContainerRef.current?.scrollToBottom();
  }, []);

  const resetInputBar = useCallback(() => {
    chatInputBarRef.current?.reset();
    setCurrentMessageFiles([]);
  }, [setCurrentMessageFiles]);

  // Add refs needed by useChatSessionController
  const chatSessionIdRef = useRef<string | null>(currentChatSessionId);
  const loadedIdSessionRef = useRef<string | null>(currentChatSessionId);
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
  const isReady = useIsReady();
  const documentSidebarVisible = useDocumentSidebarVisible();
  const updateCurrentDocumentSidebarVisible = useChatSessionStore(
    (state) => state.updateCurrentDocumentSidebarVisible
  );
  const messageHistory = useCurrentMessageHistory();

  // Determine anchor: second-to-last message (last user message before current response)
  const anchorMessage = messageHistory.at(-2) ?? messageHistory[0];
  const anchorNodeId = anchorMessage?.nodeId;
  const anchorSelector = anchorNodeId ? `#message-${anchorNodeId}` : undefined;

  // Auto-scroll preference from user settings
  const autoScrollEnabled = user?.preferences?.auto_scroll !== false;
  const isStreaming = currentChatState === "streaming";

  const { onSubmit, stopGenerating, handleMessageSpecificFileUpload } =
    useChatController({
      filterManager,
      llmManager,
      availableAssistants: agents,
      liveAssistant,
      existingChatSessionId: currentChatSessionId,
      selectedDocuments,
      searchParams,
      resetInputBar,
      setSelectedAssistantFromId,
    });

  const { onMessageSelection, currentSessionFileTokenCount } =
    useChatSessionController({
      existingChatSessionId: currentChatSessionId,
      searchParams,
      filterManager,
      firstMessage,
      setSelectedAssistantFromId,
      setSelectedDocuments,
      setCurrentMessageFiles,
      chatSessionIdRef,
      loadedIdSessionRef,
      chatInputBarRef,
      isInitialLoad,
      submitOnLoadPerformed,
      refreshChatSessions,
      onSubmit,
    });

  useSendMessageToParent();

  const retrievalEnabled = useMemo(() => {
    if (liveAssistant) {
      return personaIncludesRetrieval(liveAssistant);
    }
    return false;
  }, [liveAssistant]);

  useEffect(() => {
    if (
      (!personaIncludesRetrieval &&
        (!selectedDocuments || selectedDocuments.length === 0) &&
        documentSidebarVisible) ||
      !currentChatSessionId
    ) {
      updateCurrentDocumentSidebarVisible(false);
    }
  }, [currentChatSessionId]);

  const [stackTraceModalContent, setStackTraceModalContent] = useState<
    string | null
  >(null);

  const handleResubmitLastMessage = useCallback(() => {
    // Grab the last user-type message
    const lastUserMsg = messageHistory
      .slice()
      .reverse()
      .find((m) => m.type === "user");
    if (!lastUserMsg) {
      toast.error("No previously-submitted user message found.");
      return;
    }

    // We call onSubmit, passing a `messageOverride`
    onSubmit({
      message: lastUserMsg.message,
      currentMessageFiles: currentMessageFiles,
      deepResearch: deepResearchEnabled,
      messageIdToResend: lastUserMsg.messageId,
    });
  }, [messageHistory, onSubmit, currentMessageFiles, deepResearchEnabled]);

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

  const onChat = useCallback(
    (message: string) => {
      resetInputBar();
      onSubmit({
        message,
        currentMessageFiles,
        deepResearch: deepResearchEnabled,
      });
      if (showOnboarding) {
        finishOnboarding();
      }
    },
    [
      resetInputBar,
      onSubmit,
      currentMessageFiles,
      deepResearchEnabled,
      showOnboarding,
      finishOnboarding,
    ]
  );
  const { submit: submitQuery, classification } = useQueryController();

  const defaultAppMode =
    (user?.preferences?.default_app_mode?.toLowerCase() as "chat" | "search") ??
    "chat";

  // 1. Reset the app-mode back to the user's default when navigating back to the "New Sessions" tab.
  // 2. If we're navigating away from the "New Session" tab after performing a search, we reset the app-input-bar.
  useEffect(() => {
    if (appFocus.isNewSession()) setAppMode(defaultAppMode);
    if (!appFocus.isNewSession() && classification === "search")
      resetInputBar();
  }, [appFocus.isNewSession()]);

  const handleSearchDocumentClick = useCallback(
    (doc: MinimalOnyxDocument) => setPresentingDocument(doc),
    []
  );

  const handleAppInputBarSubmit = useCallback(
    async (message: string) => {
      // If we're in an existing chat session, always use chat mode
      // (appMode only applies to new sessions)
      if (currentChatSessionId) {
        resetInputBar();
        onSubmit({
          message,
          currentMessageFiles,
          deepResearch: deepResearchEnabled,
        });
        if (showOnboarding) {
          finishOnboarding();
        }
        return;
      }

      // For new sessions, let the query controller handle routing.
      // resetInputBar is called inside onChat for chat-routed queries.
      // For search-routed queries, the input bar is intentionally kept
      // so the user can see and refine their search query.
      await submitQuery(message, onChat);
    },
    [
      currentChatSessionId,
      submitQuery,
      onChat,
      resetInputBar,
      onSubmit,
      currentMessageFiles,
      deepResearchEnabled,
      showOnboarding,
      finishOnboarding,
    ]
  );

  // Memoized callbacks for DocumentsSidebar
  const handleMobileDocumentSidebarClose = useCallback(() => {
    updateCurrentDocumentSidebarVisible(false);
  }, [updateCurrentDocumentSidebarVisible]);

  const handleDesktopDocumentSidebarClose = useCallback(() => {
    setTimeout(() => updateCurrentDocumentSidebarVisible(false), 300);
  }, [updateCurrentDocumentSidebarVisible]);

  const desktopDocumentSidebar =
    retrievalEnabled && !settings.isMobile ? (
      <div
        className={cn(
          "flex-shrink-0 overflow-hidden transition-all duration-300 ease-in-out",
          documentSidebarVisible ? "w-[25rem]" : "w-[0rem]"
        )}
      >
        <div className="h-full w-[25rem]">
          <DocumentsSidebar
            setPresentingDocument={setPresentingDocument}
            modal={false}
            closeSidebar={handleDesktopDocumentSidebarClose}
            selectedDocuments={selectedDocuments}
          />
        </div>
      </div>
    ) : null;

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
      if (!currentChatSessionId && currentProjectId !== null) {
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
  }, [currentChatSessionId, currentProjectId, currentProjectDetails?.files]);

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
        if (currentChatSessionId) {
          const available =
            await getAvailableContextTokens(currentChatSessionId);
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
  }, [currentChatSessionId, selectedAssistant?.id, liveAssistant?.id]);

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

  const hasStarterMessages = (liveAssistant?.starter_messages?.length ?? 0) > 0;

  const isSearch = classification === "search";
  const gridStyle = {
    gridTemplateColumns: "1fr",
    gridTemplateRows: isSearch
      ? "0fr auto 1fr"
      : appFocus.isChat()
        ? "1fr auto 0fr"
        : "1fr auto 1fr",
  };

  if (!isReady) return <OnyxInitializingLoader />;

  return (
    <>
      <HealthCheckBanner />

      <AppPopup />

      {retrievalEnabled && documentSidebarVisible && settings.isMobile && (
        <div className="md:hidden">
          <Modal
            open
            onOpenChange={() => updateCurrentDocumentSidebarVisible(false)}
          >
            <Modal.Content>
              <Modal.Header
                icon={SvgFileText}
                title="Sources"
                onClose={() => updateCurrentDocumentSidebarVisible(false)}
              />
              <Modal.Body>
                {/* IMPORTANT: this is a memoized component, and it's very important
                for performance reasons that this stays true. MAKE SURE that all function
                props are wrapped in useCallback. */}
                <DocumentsSidebar
                  setPresentingDocument={setPresentingDocument}
                  modal
                  closeSidebar={handleMobileDocumentSidebarClose}
                  selectedDocuments={selectedDocuments}
                />
              </Modal.Body>
            </Modal.Content>
          </Modal>
        </div>
      )}

      {presentingDocument && (
        <TextViewModal
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

      <AppLayouts.Root enableBackground>
        <Dropzone
          onDrop={(acceptedFiles) =>
            handleMessageSpecificFileUpload(acceptedFiles)
          }
          noClick
        >
          {({ getRootProps }) => (
            <div
              className="h-full w-full flex flex-col items-center outline-none relative"
              {...getRootProps({ tabIndex: -1 })}
            >
              {/* Main content grid — 3 rows, animated */}
              <div
                className="flex-1 w-full grid min-h-0 transition-[grid-template-rows] duration-150 ease-in-out"
                style={gridStyle}
              >
                {/* ── Top row: ChatUI / WelcomeMessage / ProjectUI ── */}
                <div className="row-start-1 min-h-0 overflow-hidden flex flex-col items-center">
                  {/* ChatUI */}
                  <Fade
                    show={
                      appFocus.isChat() &&
                      !!currentChatSessionId &&
                      !!liveAssistant
                    }
                    className="h-full w-full flex flex-col items-center"
                  >
                    <ChatScrollContainer
                      ref={scrollContainerRef}
                      sessionId={currentChatSessionId!}
                      anchorSelector={anchorSelector}
                      autoScroll={autoScrollEnabled}
                      isStreaming={isStreaming}
                      onScrollButtonVisibilityChange={setShowScrollButton}
                    >
                      <ChatUI
                        liveAssistant={liveAssistant!}
                        llmManager={llmManager}
                        deepResearchEnabled={deepResearchEnabled}
                        currentMessageFiles={currentMessageFiles}
                        setPresentingDocument={setPresentingDocument}
                        onSubmit={onSubmit}
                        onMessageSelection={onMessageSelection}
                        stopGenerating={stopGenerating}
                        onResubmit={handleResubmitLastMessage}
                        anchorNodeId={anchorNodeId}
                      />
                    </ChatScrollContainer>
                  </Fade>

                  {/* ProjectUI */}
                  {appFocus.isProject() && (
                    <ProjectContextPanel
                      projectTokenCount={projectContextTokenCount}
                      availableContextTokens={availableContextTokens}
                      setPresentingDocument={setPresentingDocument}
                    />
                  )}

                  {/* WelcomeMessageUI */}
                  <Fade
                    show={
                      (appFocus.isNewSession() || appFocus.isAgent()) &&
                      !classification
                    }
                    className="w-full flex-1 flex flex-col items-center justify-end"
                  >
                    <WelcomeMessage
                      agent={liveAssistant}
                      isDefaultAgent={isDefaultAgent}
                    />
                    <Spacer rem={1.5} />
                  </Fade>
                </div>

                {/* ── Middle-center: AppInputBar ── */}
                <div className="row-start-2 flex flex-col items-center">
                  <div className="relative w-full max-w-[var(--app-page-main-content-width)] flex flex-col">
                    {/* Scroll to bottom button - positioned absolutely above AppInputBar */}
                    {appFocus.isChat() && showScrollButton && (
                      <div className="absolute top-[-3.5rem] self-center">
                        <Button
                          icon={SvgChevronDown}
                          onClick={handleScrollToBottom}
                          aria-label="Scroll to bottom"
                          prominence="secondary"
                        />
                      </div>
                    )}

                    {/* OnboardingUI */}
                    {(appFocus.isNewSession() || appFocus.isAgent()) &&
                      !classification &&
                      (showOnboarding ||
                        (user?.role !== UserRole.ADMIN &&
                          !user?.personalization?.name)) && (
                        <OnboardingFlow
                          handleHideOnboarding={hideOnboarding}
                          handleFinishOnboarding={finishOnboarding}
                          state={onboardingState}
                          actions={onboardingActions}
                          llmDescriptors={llmDescriptors}
                        />
                      )}

                    {/*
                      # Note (@raunakab)

                      `shadow-01` on AppInputBar extends ~14px below the element
                      (2px offset + 12px blur). Because the content area in `Root`
                      (app-layouts.tsx) uses `overflow-auto`, shadows that exceed
                      the container bounds are clipped.

                      The animated spacer divs above and below the AppInputBar
                      provide 14px of breathing room so the shadow renders fully.
                      They transition between h-0 and h-[14px] depending on whether
                      the classification is "search" (spacer above) or "chat"
                      (spacer below).

                      There is a corresponding note inside `app-layouts.tsx`
                      (Footer) that explains why the Footer removes its top
                      padding during chat to compensate for this extra space.
                    */}
                    <div>
                      <div
                        className={cn(
                          "transition-all duration-150 ease-in-out overflow-hidden",
                          classification === "search" ? "h-[14px]" : "h-0"
                        )}
                      />
                      <AppInputBar
                        ref={chatInputBarRef}
                        deepResearchEnabled={deepResearchEnabled}
                        toggleDeepResearch={toggleDeepResearch}
                        toggleDocumentSidebar={toggleDocumentSidebar}
                        filterManager={filterManager}
                        llmManager={llmManager}
                        removeDocs={() => setSelectedDocuments([])}
                        retrievalEnabled={retrievalEnabled}
                        selectedDocuments={selectedDocuments}
                        initialMessage={
                          searchParams?.get(SEARCH_PARAM_NAMES.USER_PROMPT) ||
                          ""
                        }
                        stopGenerating={stopGenerating}
                        onSubmit={handleAppInputBarSubmit}
                        chatState={currentChatState}
                        currentSessionFileTokenCount={
                          currentChatSessionId
                            ? currentSessionFileTokenCount
                            : projectContextTokenCount
                        }
                        availableContextTokens={availableContextTokens}
                        selectedAssistant={selectedAssistant || liveAssistant}
                        handleFileUpload={handleMessageSpecificFileUpload}
                        setPresentingDocument={setPresentingDocument}
                        disabled={
                          (!llmManager.isLoadingProviders &&
                            llmManager.hasAnyProvider === false) ||
                          (!isLoadingOnboarding &&
                            onboardingState.currentStep !==
                              OnboardingStep.Complete)
                        }
                      />
                      <div
                        className={cn(
                          "transition-all duration-150 ease-in-out overflow-hidden",
                          appFocus.isChat() ? "h-[14px]" : "h-0"
                        )}
                      />
                    </div>

                    {/* ProjectChatSessionsUI */}
                    {appFocus.isProject() && (
                      <>
                        <Spacer rem={0.5} />
                        <ProjectChatSessionList />
                      </>
                    )}
                  </div>
                </div>

                {/* ── Bottom: SearchResults + SourceFilter / Suggestions ── */}
                <div className="row-start-3 min-h-0 overflow-hidden flex flex-col items-center w-full">
                  {/* SuggestionsUI */}
                  <Fade
                    show={
                      (appFocus.isNewSession() || appFocus.isAgent()) &&
                      hasStarterMessages
                    }
                    className="h-full flex-1 w-full max-w-[var(--app-page-main-content-width)]"
                  >
                    <Spacer rem={0.5} />
                    <Suggestions onSubmit={onSubmit} />
                  </Fade>

                  {/* SearchUI */}
                  <Fade
                    show={isSearch}
                    className="h-full flex-1 w-full max-w-[var(--app-page-main-content-width)] px-1 flex flex-col"
                  >
                    <Spacer rem={0.75} />
                    <SearchUI onDocumentClick={handleSearchDocumentClick} />
                  </Fade>
                </div>
              </div>
            </div>
          )}
        </Dropzone>
      </AppLayouts.Root>

      {desktopDocumentSidebar}
    </>
  );
}
