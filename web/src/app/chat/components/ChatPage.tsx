"use client";

import { redirect, useRouter, useSearchParams } from "next/navigation";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  personaIncludesRetrieval,
  getAvailableContextTokens,
} from "@/app/chat/services/lib";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { useFederatedConnectors, useFilters, useLlmManager } from "@/lib/hooks";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import OnyxInitializingLoader from "@/components/OnyxInitializingLoader";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import Dropzone from "react-dropzone";
import ChatInputBar, {
  ChatInputBarHandle,
} from "@/app/chat/components/input/ChatInputBar";
import useChatSessions from "@/hooks/useChatSessions";
import useCCPairs from "@/hooks/useCCPairs";
import { useTags } from "@/lib/hooks/useTags";
import { useDocumentSets } from "@/lib/hooks/useDocumentSets";
import { useAgents } from "@/hooks/useAgents";
import { ChatPopup } from "@/app/chat/components/ChatPopup";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { useUser } from "@/components/user/UserProvider";
import NoAssistantModal from "@/components/modals/NoAssistantModal";
import TextView from "@/components/chat/TextView";
import Modal from "@/refresh-components/Modal";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import { getSourceMetadata } from "@/lib/sources";
import { SourceMetadata } from "@/lib/search/interfaces";
import { FederatedConnectorDetail, UserRole, ValidSources } from "@/lib/types";
import DocumentsSidebar from "@/sections/document-sidebar/DocumentsSidebar";
import { useChatController } from "@/app/chat/hooks/useChatController";
import { useAssistantController } from "@/app/chat/hooks/useAssistantController";
import { useChatSessionController } from "@/app/chat/hooks/useChatSessionController";
import { useDeepResearchToggle } from "@/app/chat/hooks/useDeepResearchToggle";
import { useIsDefaultAgent } from "@/app/chat/hooks/useIsDefaultAgent";
import {
  useChatSessionStore,
  useCurrentMessageHistory,
} from "@/app/chat/stores/useChatSessionStore";
import {
  useCurrentChatState,
  useIsReady,
  useDocumentSidebarVisible,
} from "@/app/chat/stores/useChatSessionStore";
import FederatedOAuthModal from "@/components/chat/FederatedOAuthModal";
import ChatUI, { ChatUIHandle } from "@/sections/ChatUI";
import WelcomeMessage from "@/app/chat/components/WelcomeMessage";
import ProjectContextPanel from "@/app/chat/components/projects/ProjectContextPanel";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import {
  getProjectTokenCount,
  getMaxSelectedDocumentTokens,
} from "@/app/chat/projects/projectsService";
import ProjectChatSessionList from "@/app/chat/components/projects/ProjectChatSessionList";
import { cn } from "@/lib/utils";
import Suggestions from "@/sections/Suggestions";
import OnboardingFlow from "@/refresh-components/onboarding/OnboardingFlow";
import { OnboardingStep } from "@/refresh-components/onboarding/types";
import { useShowOnboarding } from "@/hooks/useShowOnboarding";
import * as AppLayouts from "@/layouts/app-layouts";
import { SvgFileText } from "@opal/icons";
import Spacer from "@/refresh-components/Spacer";
import { DEFAULT_CONTEXT_TOKENS } from "@/lib/constants";

export interface ChatPageProps {
  firstMessage?: string;
}

export default function ChatPage({ firstMessage }: ChatPageProps) {
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
    useAssistantController({
      selectedChatSession: currentChatSession,
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

  const [projectPanelVisible, setProjectPanelVisible] = useState(true);
  const chatInputBarRef = useRef<ChatInputBarHandle>(null);

  const filterManager = useFilters();

  const isDefaultAgent = useIsDefaultAgent({
    liveAssistant,
    existingChatSessionId: currentChatSessionId,
    selectedChatSession: currentChatSession ?? undefined,
    settings,
  });

  const chatUiRef = useRef<ChatUIHandle>(null);
  const autoScrollEnabled = user?.preferences?.auto_scroll ?? false;

  // Handle input bar height changes for scroll adjustment
  const handleInputHeightChange = useCallback(
    (delta: number) => {
      if (autoScrollEnabled && delta > 0) {
        chatUiRef.current?.scrollBy(delta);
      }
    },
    [autoScrollEnabled]
  );

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

  const { onSubmit, stopGenerating, handleMessageSpecificFileUpload } =
    useChatController({
      filterManager,
      llmManager,
      availableAssistants: agents,
      liveAssistant,
      existingChatSessionId: currentChatSessionId,
      selectedDocuments,
      searchParams,
      setPopup,
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
      deepResearch: deepResearchEnabled,
      messageIdToResend: lastUserMsg.messageId,
    });
  }, [
    messageHistory,
    setPopup,
    onSubmit,
    currentMessageFiles,
    deepResearchEnabled,
  ]);

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

  const handleChatInputSubmit = useCallback(
    (message: string) => {
      onSubmit({
        message,
        currentMessageFiles: currentMessageFiles,
        deepResearch: deepResearchEnabled,
      });
      if (showOnboarding) {
        finishOnboarding();
      }
    },
    [
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

  useEffect(() => {
    if (!!currentProjectId && !currentChatSessionId) {
      setProjectPanelVisible(true);
    }
    if (!!currentChatSessionId) {
      setProjectPanelVisible(false);
    }
  }, [currentProjectId, currentChatSessionId]);

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

  if (!isReady) return <OnyxInitializingLoader />;

  return (
    <>
      <HealthCheckBanner />

      {/* ChatPopup is a custom popup that displays a admin-specified message on initial user visit.
      Only used in the EE version of the app. */}
      {popup}

      <ChatPopup />

      {retrievalEnabled && documentSidebarVisible && settings.isMobile && (
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

      <AppLayouts.Root>
        <Dropzone
          onDrop={(acceptedFiles) =>
            handleMessageSpecificFileUpload(acceptedFiles)
          }
          noClick
        >
          {({ getRootProps }) => (
            <div
              className="h-full w-full flex flex-col items-center outline-none"
              {...getRootProps({ tabIndex: -1 })}
            >
              {/* ProjectUI */}
              {!!currentProjectId && projectPanelVisible && (
                <ProjectContextPanel
                  projectTokenCount={projectContextTokenCount}
                  availableContextTokens={availableContextTokens}
                  setPresentingDocument={setPresentingDocument}
                />
              )}

              {/* ChatUI */}
              {!!currentChatSessionId && (
                <ChatUI
                  ref={chatUiRef}
                  liveAssistant={liveAssistant}
                  llmManager={llmManager}
                  deepResearchEnabled={deepResearchEnabled}
                  currentMessageFiles={currentMessageFiles}
                  setPresentingDocument={setPresentingDocument}
                  onSubmit={onSubmit}
                  onMessageSelection={onMessageSelection}
                  stopGenerating={stopGenerating}
                  handleResubmitLastMessage={handleResubmitLastMessage}
                />
              )}

              {!currentChatSessionId && !currentProjectId && (
                <div className="w-full flex-1 flex flex-col items-center justify-end">
                  <WelcomeMessage
                    agent={liveAssistant}
                    isDefaultAgent={isDefaultAgent}
                  />
                  <Spacer rem={1.5} />
                </div>
              )}

              {/* ChatInputBar container */}
              <div className="w-[min(50rem,100%)] pointer-events-auto z-sticky flex flex-col px-4 justify-center items-center">
                {(showOnboarding ||
                  (user?.role !== UserRole.ADMIN &&
                    !user?.personalization?.name)) &&
                  currentProjectId === null && (
                    <OnboardingFlow
                      handleHideOnboarding={hideOnboarding}
                      state={onboardingState}
                      actions={onboardingActions}
                      llmDescriptors={llmDescriptors}
                    />
                  )}

                <ChatInputBar
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
                    searchParams?.get(SEARCH_PARAM_NAMES.USER_PROMPT) || ""
                  }
                  stopGenerating={stopGenerating}
                  onSubmit={handleChatInputSubmit}
                  onHeightChange={handleInputHeightChange}
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
                      onboardingState.currentStep !== OnboardingStep.Complete)
                  }
                />

                <Spacer rem={0.5} />

                {!!currentProjectId && <ProjectChatSessionList />}
              </div>

              {/* SearchUI */}
              {!currentChatSessionId && !currentProjectId && (
                <div className="flex flex-1 flex-col items-center w-full">
                  {liveAssistant?.starter_messages &&
                    liveAssistant.starter_messages.length > 0 &&
                    messageHistory.length === 0 &&
                    !currentProjectId &&
                    !currentChatSessionId && (
                      <div className="max-w-[50rem] w-full">
                        <Suggestions onSubmit={onSubmit} />
                      </div>
                    )}
                </div>
              )}
            </div>
          )}
        </Dropzone>
      </AppLayouts.Root>

      {desktopDocumentSidebar}
    </>
  );
}
