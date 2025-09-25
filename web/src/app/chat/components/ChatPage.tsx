"use client";

import { redirect, useRouter, useSearchParams } from "next/navigation";
import { ChatSession, ChatSessionSharedStatus } from "@/app/chat/interfaces";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { useScrollonStream } from "@/app/chat/services/lib";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { useFederatedConnectors, useFilters, useLlmManager } from "@/lib/hooks";
import { useFederatedOAuthStatus } from "@/lib/hooks/useFederatedOAuthStatus";
import { FeedbackType } from "@/app/chat/interfaces";
import { OnyxInitializingLoader } from "@/components/OnyxInitializingLoader";
import { FeedbackModal } from "@/app/chat/components/modal/FeedbackModal";
import { ShareChatSessionModal } from "@/app/chat/components/modal/ShareChatSessionModal";
import { FiArrowDown } from "react-icons/fi";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import Dropzone from "react-dropzone";
import { ChatInputBar } from "@/app/chat/components/input/ChatInputBar";
import { useChatContext } from "@/components/context/ChatContext";
import { ChatPopup } from "@/app/chat/components/ChatPopup";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { useUser } from "@/components/user/UserProvider";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import { NoAssistantModal } from "@/components/modals/NoAssistantModal";
import { useAssistantsContext } from "@/components/context/AssistantsContext";
import TextView from "@/components/chat/TextView";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import { getSourceMetadata } from "@/lib/sources";
import { FilePickerModal } from "@/app/chat/my-documents/components/FilePicker";
import { SourceMetadata } from "@/lib/search/interfaces";
import { FederatedConnectorDetail, ValidSources } from "@/lib/types";
import { useDocumentsContext } from "@/app/chat/my-documents/DocumentsContext";
import { ChatSearchModal } from "@/app/chat/chat_search/ChatSearchModal";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
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
  useChatSessionSharedStatus,
  useHasSentLocalUserMessage,
} from "@/app/chat/stores/useChatSessionStore";
import { FederatedOAuthModal } from "@/components/chat/FederatedOAuthModal";
import { StarterMessageDisplay } from "@/app/chat/components/starterMessages/StarterMessageDisplay";
import { MessagesDisplay } from "@/app/chat/components/MessagesDisplay";
import { OnyxIcon } from "@/components/icons/icons";

export interface ChatPageProps {
  firstMessage?: string;
}

export function ChatPage({ firstMessage }: ChatPageProps) {
  // Performance tracking
  // Keeping this here in case we need to track down slow renders in the future
  // const renderCount = useRef(0);
  // renderCount.current++;
  // const renderStartTime = performance.now();

  const router = useRouter();
  const searchParams = useSearchParams();
  const {
    currentChatId,
    currentChat,
    ccPairs,
    tags,
    documentSets,
    llmProviders,
    shouldShowWelcomeModal,
    refreshChatSessions,
  } = useChatContext();
  const {
    selectedFiles,
    selectedFolders,
    clearSelectedItems,
    currentMessageFiles,
    setCurrentMessageFiles,
  } = useDocumentsContext();
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // handle redirect if chat page is disabled
  // NOTE: this must be done here, in a client component since
  // settings are passed in via Context and therefore aren't
  // available in server-side components
  const settings = useSettingsContext();
  const enterpriseSettings = settings?.enterpriseSettings;
  const [toggleDocSelection, setToggleDocSelection] = useState(false);
  const isInitialLoad = useRef(true);
  const { assistants: availableAssistants } = useAssistantsContext();
  const [showApiKeyModal, setShowApiKeyModal] = useState(
    !shouldShowWelcomeModal
  );
  // Also fetch federated connectors for the sources list
  const { data: federatedConnectorsData } = useFederatedConnectors();
  const { user, isAdmin } = useUser();

  const processSearchParamsAndSubmitMessage = (searchParamsString: string) => {
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
        selectedFiles,
        selectedFolders,
        currentMessageFiles,
        useAgentSearch: deepResearchEnabled,
      });
    }
  };

  const { selectedAssistant, setSelectedAssistantFromId, liveAssistant } =
    useAssistantController({
      selectedChatSession: currentChat,
    });

  const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({
    chatSessionId: currentChatId,
    assistantId: selectedAssistant?.id,
  });
  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);
  const llmManager = useLlmManager(
    llmProviders,
    currentChat || undefined,
    liveAssistant
  );

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
  const [message, setMessage] = useState(
    searchParams?.get(SEARCH_PARAM_NAMES.USER_PROMPT) || ""
  );
  const filterManager = useFilters();
  const [isChatSearchModalOpen, setIsChatSearchModalOpen] = useState(false);
  const [currentFeedback, setCurrentFeedback] = useState<
    [FeedbackType, number] | null
  >(null);
  const [sharingModalVisible, setSharingModalVisible] =
    useState<boolean>(false);
  const [aboveHorizon, setAboveHorizon] = useState(false);
  const scrollableDivRef = useRef<HTMLDivElement>(null);
  const lastMessageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLDivElement>(null);
  const endDivRef = useRef<HTMLDivElement>(null);
  const scrollInitialized = useRef(false);
  const scrollDist = useRef<number>(0);

  const resetInputBar = useCallback(() => {
    setMessage("");
    setCurrentMessageFiles([]);
  }, [setMessage, setCurrentMessageFiles]);

  // handle re-sizing of the text area
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  // Add refs needed by useChatSessionController
  const chatSessionIdRef = useRef<string | null>(currentChatId);
  const loadedIdSessionRef = useRef<string | null>(currentChatId);
  const submitOnLoadPerformed = useRef<boolean>(false);

  // used for resizing of the document sidebar
  const masterFlexboxRef = useRef<HTMLDivElement>(null);

  const loadNewPageLogic = (event: MessageEvent) => {
    if (event.data.type === SUBMIT_MESSAGE_TYPES.PAGE_CHANGE) {
      try {
        const url = new URL(event.data.href);
        processSearchParamsAndSubmitMessage(url.searchParams.toString());
      } catch (error) {
        console.error("Error parsing URL:", error);
      }
    }
  };

  // Reset scroll state when switching chat sessions
  useEffect(() => {
    scrollDist.current = 0;
    setAboveHorizon(false);
  }, [currentChatId]);
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
  const submittedMessage = useSubmittedMessage();
  const loadingError = useLoadingError();
  const uncaughtError = useUncaughtError();
  const isReady = useIsReady();
  const isFetchingChatMessages = useIsFetching();
  const messageHistory = useCurrentMessageHistory();
  const hasPerformedInitialScroll = useHasPerformedInitialScroll();
  const documentSidebarVisible = useDocumentSidebarVisible();
  const chatSessionSharedStatus = useChatSessionSharedStatus();
  const updateHasPerformedInitialScroll = useChatSessionStore(
    (state) => state.updateHasPerformedInitialScroll
  );
  const updateCurrentDocumentSidebarVisible = useChatSessionStore(
    (state) => state.updateCurrentDocumentSidebarVisible
  );
  const updateCurrentChatSessionSharedStatus = useChatSessionStore(
    (state) => state.updateCurrentChatSessionSharedStatus
  );

  const clientScrollToBottom = useCallback(() => {
    // Clear any existing scroll timeout to debounce rapid calls
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current);
    }

    // Debounce rapid scroll calls
    scrollTimeoutRef.current = setTimeout(() => {
      // Use requestAnimationFrame to ensure DOM updates are complete
      const scrollToBottom = () => {
        if (!endDivRef.current || !scrollableDivRef.current) {
          console.error("endDivRef or scrollableDivRef not found");
          return;
        }

        const rect = endDivRef.current.getBoundingClientRect();
        const containerRect = scrollableDivRef.current.getBoundingClientRect();

        // Check if the end div is already visible within the scrollable container
        const isVisible =
          rect.top >= containerRect.top && rect.bottom <= containerRect.bottom;

        if (isVisible) return;

        // For smooth scrolling, use a more controlled approach
        const targetScrollTop =
          scrollableDivRef.current.scrollHeight -
          scrollableDivRef.current.clientHeight;

        // Use scrollTo with smooth behavior for better control
        scrollableDivRef.current.scrollTo({
          top: targetScrollTop,
          behavior: "smooth",
        });

        if (chatSessionIdRef.current) {
          updateHasPerformedInitialScroll(chatSessionIdRef.current, true);
        }
      };

      // Use requestAnimationFrame to ensure DOM updates are complete
      requestAnimationFrame(() => {
        requestAnimationFrame(scrollToBottom);
      });
    }, 16);
    // 16ms debounce for smooth scrolling, immediate for fast
  }, [updateHasPerformedInitialScroll]);

  const { onSubmit, stopGenerating, handleMessageSpecificFileUpload } =
    useChatController({
      filterManager,
      llmManager,
      availableAssistants,
      liveAssistant,
      existingChatSessionId: currentChatId,
      selectedDocuments,
      searchParams,
      setPopup,
      clientScrollToBottom,
      resetInputBar,
      setSelectedAssistantFromId,
    });

  const { onMessageSelection } = useChatSessionController({
    existingChatSessionId: currentChatId,
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
    clearSelectedItems,
    refreshChatSessions,
    onSubmit,
  });

  const autoScrollEnabled = user?.preferences?.auto_scroll ?? false;

  useScrollonStream({
    chatState: currentChatState,
    scrollableDivRef,
    scrollDist,
    endDivRef,
    debounceNumber: 100,
    mobile: settings?.isMobile,
    enableAutoScroll: autoScrollEnabled,
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

  const [stackTraceModalContent, setStackTraceModalContent] = useState<
    string | null
  >(null);

  const [sharedChatSession, setSharedChatSession] =
    useState<ChatSession | null>();

  const handleResubmitLastMessage = () => {
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
      selectedFiles,
      selectedFolders: selectedFolders,
      currentMessageFiles: currentMessageFiles,
      useAgentSearch: deepResearchEnabled,
      messageIdToResend: lastUserMsg.messageId,
    });
  };

  const toggleDocumentSidebar = useCallback(() => {
    if (!documentSidebarVisible) {
      updateCurrentDocumentSidebarVisible(true);
    } else {
      updateCurrentDocumentSidebarVisible(false);
    }
  }, [documentSidebarVisible, updateCurrentDocumentSidebarVisible]);

  const clearSelectedDocuments = useCallback(() => {
    setSelectedDocuments([]);
    clearSelectedItems();
  }, [clearSelectedItems]);

  // Memoized callbacks for ChatInputBar
  const handleToggleDocSelection = useCallback(() => {
    setToggleDocSelection(true);
  }, []);

  const handleShowApiKeyModal = useCallback(() => {
    setShowApiKeyModal(true);
  }, []);

  const handleChatInputSubmit = useCallback(() => {
    onSubmit({
      message: message,
      selectedFiles: selectedFiles,
      selectedFolders: selectedFolders,
      currentMessageFiles: currentMessageFiles,
      useAgentSearch: deepResearchEnabled,
    });
  }, [
    message,
    onSubmit,
    selectedFiles,
    selectedFolders,
    currentMessageFiles,
    deepResearchEnabled,
  ]);

  if (!user) {
    redirect("/auth/login");
  }

  // handle error case where no assistants are available
  const noAssistants = liveAssistant === null || liveAssistant === undefined;
  if (noAssistants) {
    return (
      <>
        <HealthCheckBanner />
        <NoAssistantModal isAdmin={isAdmin} />
      </>
    );
  }

  if (!isReady) {
    return (
      <div className="h-full flex">
        <OnyxInitializingLoader />
      </div>
    );
  }

  // Determine whether to show the centered input (no messages yet)
  const showCenteredInput =
    messageHistory.length === 0 &&
    !isFetchingChatMessages &&
    !loadingError &&
    !submittedMessage;

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

      {currentFeedback && (
        <FeedbackModal
          feedbackType={currentFeedback[0]}
          messageId={currentFeedback[1]}
          onClose={() => setCurrentFeedback(null)}
          setPopup={setPopup}
        />
      )}

      {toggleDocSelection && (
        <FilePickerModal
          setPresentingDocument={setPresentingDocument}
          buttonContent="Set as Context"
          isOpen={true}
          onClose={() => setToggleDocSelection(false)}
          onSave={() => {
            setToggleDocSelection(false);
          }}
        />
      )}

      <ChatSearchModal
        open={isChatSearchModalOpen}
        onCloseModal={() => setIsChatSearchModalOpen(false)}
      />

      {/* {retrievalEnabled && documentSidebarVisible && settings?.isMobile && (
        <div className="md:hidden">
          <Modal
            hideDividerForTitle
            onOutsideClick={() => updateCurrentDocumentSidebarVisible(false)}
            title="Sources"
          >
            <DocumentResults
              setPresentingDocument={setPresentingDocument}
              modal={true}
              ref={innerSidebarElementRef}
              closeSidebar={handleMobileDocumentSidebarClose}
              selectedDocuments={selectedDocuments}
              toggleDocumentSelection={toggleDocumentSelection}
              clearSelectedDocuments={clearSelectedDocuments}
              // TODO (chris): fix
              selectedDocumentTokens={0}
              maxTokens={maxTokens}
              initialWidth={400}
              isOpen={true}
            />
          </Modal>
        </div>
      )} */}

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

      {sharedChatSession && (
        <ShareChatSessionModal
          assistantId={liveAssistant?.id}
          message={message}
          modelOverride={llmManager.currentLlm}
          chatSessionId={sharedChatSession.id}
          existingSharedStatus={sharedChatSession.shared_status}
          onClose={() => setSharedChatSession(null)}
          onShare={(shared) =>
            updateCurrentChatSessionSharedStatus(
              shared
                ? ChatSessionSharedStatus.Public
                : ChatSessionSharedStatus.Private
            )
          }
        />
      )}

      {sharingModalVisible && chatSessionId !== null && (
        <ShareChatSessionModal
          message={message}
          assistantId={liveAssistant?.id}
          modelOverride={llmManager.currentLlm}
          chatSessionId={chatSessionId}
          existingSharedStatus={chatSessionSharedStatus}
          onClose={() => setSharingModalVisible(false)}
        />
      )}

      <FederatedOAuthModal />

      {/* <div
          style={{ transition: "width 0.30s ease-out" }}
          className={`
              flex-none 
              fixed
              right-0
              h-screen
              transition-all
              duration-300
              ease-in-out
              bg-transparent
              transition-all
              duration-300
              ease-in-out
              h-full
              ${
                documentSidebarVisible && !settings?.isMobile
                  ? "w-[400px]"
                  : "w-[0px]"
              }
          `}
        >
          <DocumentResults
            setPresentingDocument={setPresentingDocument}
            modal={false}
            ref={innerSidebarElementRef}
            closeSidebar={handleDesktopDocumentSidebarClose}
            selectedDocuments={selectedDocuments}
            toggleDocumentSelection={toggleDocumentSelection}
            clearSelectedDocuments={clearSelectedDocuments}
            // TODO (chris): fix
            selectedDocumentTokens={0}
            maxTokens={maxTokens}
            initialWidth={400}
            isOpen={documentSidebarVisible && !settings?.isMobile}
          />
        </div> */}

      <div
        id="scrollableContainer"
        className="flex h-full w-full relative flex-col overflow-y-hidden"
        ref={masterFlexboxRef}
      >
        <Dropzone
          key={chatSessionId}
          onDrop={(acceptedFiles) =>
            handleMessageSpecificFileUpload(acceptedFiles)
          }
          noClick
        >
          {({ getRootProps }) => (
            <div
              className="h-full w-full flex flex-col pb-padding-content"
              {...getRootProps()}
            >
              <div
                ref={scrollableDivRef}
                className={`${showCenteredInput ? "h-[0rem]" : "h-full"} flex flex-col no-scrollbar overflow-y-scroll relative py-padding-button`}
              >
                <MessagesDisplay
                  setCurrentFeedback={setCurrentFeedback}
                  onSubmit={onSubmit}
                  onMessageSelection={onMessageSelection}
                  stopGenerating={stopGenerating}
                  uncaughtError={uncaughtError}
                  handleResubmitLastMessage={handleResubmitLastMessage}
                  lastMessageRef={lastMessageRef}
                  endDivRef={endDivRef}
                />

                {/* {!showCenteredInput && aboveHorizon && (
                  <div className="flex sticky w-full">
                    <button
                      onClick={() => clientScrollToBottom()}
                      className="p-1 pointer-events-auto text-neutral-700 rounded-2xl bg-neutral-200 border border-border  mx-auto "
                    >
                      <FiArrowDown size={18} />
                    </button>
                  </div>
                )} */}
              </div>

              <div
                ref={inputRef}
                className={`relative flex flex-col justify-center items-center ${showCenteredInput && "h-full"} gap-padding-content px-padding-content`}
              >
                {showCenteredInput && (
                  // Need the `className=""` here, unfortunately, since the default value messes things up...
                  <OnyxIcon size={50} className="" />
                )}

                <ChatInputBar
                  deepResearchEnabled={deepResearchEnabled}
                  toggleDeepResearch={toggleDeepResearch}
                  toggleDocumentSidebar={toggleDocumentSidebar}
                  filterManager={filterManager}
                  llmManager={llmManager}
                  removeDocs={clearSelectedDocuments}
                  retrievalEnabled={retrievalEnabled}
                  toggleDocSelection={handleToggleDocSelection}
                  showConfigureAPIKey={handleShowApiKeyModal}
                  selectedDocuments={selectedDocuments}
                  message={message}
                  setMessage={setMessage}
                  stopGenerating={stopGenerating}
                  onSubmit={handleChatInputSubmit}
                  chatState={currentChatState}
                  selectedAssistant={selectedAssistant || liveAssistant}
                  handleFileUpload={handleMessageSpecificFileUpload}
                  textAreaRef={textAreaRef}
                />

                {liveAssistant.starter_messages &&
                  liveAssistant.starter_messages.length > 0 &&
                  messageHistory.length === 0 &&
                  showCenteredInput && (
                    <StarterMessageDisplay
                      starterMessages={liveAssistant.starter_messages}
                      onSelectStarterMessage={(message) =>
                        onSubmit({
                          message: message,
                          selectedFiles: selectedFiles,
                          selectedFolders: selectedFolders,
                          currentMessageFiles: currentMessageFiles,
                          useAgentSearch: deepResearchEnabled,
                        })
                      }
                    />
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
                    <div className="hidden lg:block fixed right-12 bottom-8 pointer-events-none">
                      <img
                        src="/api/enterprise-settings/logotype"
                        alt="logotype"
                        style={{ objectFit: "contain" }}
                        className="w-fit h-9"
                      />
                    </div>
                  )}
              </div>
            </div>
          )}
        </Dropzone>
      </div>
    </>
  );
}
