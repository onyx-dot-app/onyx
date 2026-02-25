"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { useUser } from "@/providers/UserProvider";
import { toast } from "@/hooks/useToast";
import { AuthType } from "@/lib/constants";
import Button from "@/refresh-components/buttons/Button";
import AppInputBar, { AppInputBarHandle } from "@/sections/input/AppInputBar";
import IconButton from "@/refresh-components/buttons/IconButton";
import Modal from "@/refresh-components/Modal";
import { useFilters, useLlmManager } from "@/lib/hooks";
import Dropzone from "react-dropzone";
import { useSendMessageToParent, getPanelOrigin } from "@/lib/extension/utils";
import { useNRFPreferences } from "@/components/context/NRFPreferencesContext";
import SidePanelHeader from "@/app/nrf/side-panel/SidePanelHeader";
import { CHROME_MESSAGE } from "@/lib/extension/constants";
import { SettingsPanel } from "@/app/components/nrf/SettingsPanel";
import LoginPage from "@/app/auth/login/LoginPage";
import { sendSetDefaultNewTabMessage } from "@/lib/extension/utils";
import { useAgents } from "@/hooks/useAgents";
import { useProjectsContext } from "@/providers/ProjectsContext";
import useDeepResearchToggle from "@/hooks/useDeepResearchToggle";
import useChatController from "@/hooks/useChatController";
import useChatSessionController from "@/hooks/useChatSessionController";
import useAgentController from "@/hooks/useAgentController";
import {
  useCurrentChatState,
  useCurrentMessageHistory,
  useChatSessionStore,
  useDocumentSidebarVisible,
} from "@/app/app/stores/useChatSessionStore";
import ChatUI from "@/sections/chat/ChatUI";
import ChatScrollContainer from "@/sections/chat/ChatScrollContainer";
import WelcomeMessage from "@/app/app/components/WelcomeMessage";
import useChatSessions from "@/hooks/useChatSessions";
import { cn } from "@/lib/utils";
import Spacer from "@/refresh-components/Spacer";
import { DEFAULT_CONTEXT_TOKENS } from "@/lib/constants";
import { SvgUser, SvgMenu, SvgAlertTriangle } from "@opal/icons";
import { useAppBackground } from "@/providers/AppBackgroundProvider";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import DocumentsSidebar from "@/sections/document-sidebar/DocumentsSidebar";
import TextViewModal from "@/sections/modals/TextViewModal";
import { personaIncludesRetrieval } from "@/app/app/services/lib";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { eeGated } from "@/ce";
import EESearchUI from "@/ee/sections/SearchUI";

const SearchUI = eeGated(EESearchUI);

interface NRFPageProps {
  isSidePanel?: boolean;
}

// Reserve half of the context window for the model's response output
const AVAILABLE_CONTEXT_TOKENS = Number(DEFAULT_CONTEXT_TOKENS) * 0.5;

export default function NRFPage({ isSidePanel = false }: NRFPageProps) {
  const { setUseOnyxAsNewTab } = useNRFPreferences();

  const searchParams = useSearchParams();
  const filterManager = useFilters();
  const { user, authTypeMetadata } = useUser();

  // Chat sessions
  const { refreshChatSessions } = useChatSessions();
  const existingChatSessionId = null; // NRF always starts new chats

  // Get agents for assistant selection
  const { agents: availableAssistants } = useAgents();

  // Projects context for file handling
  const {
    currentMessageFiles,
    setCurrentMessageFiles,
    lastFailedFiles,
    clearLastFailedFiles,
  } = useProjectsContext();

  // Show toast if any files failed
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

  // Assistant controller
  const { selectedAssistant, setSelectedAssistantFromId, liveAssistant } =
    useAgentController({
      selectedChatSession: undefined,
      onAssistantSelect: () => {},
    });

  // LLM manager for model selection.
  // - currentChatSession: undefined because NRF always starts new chats
  // - liveAssistant: uses the selected assistant, or undefined to fall back
  //   to system-wide default LLM provider.
  //
  // If no LLM provider is configured (e.g., fresh signup), the input bar is
  // disabled and a "Set up an LLM" button is shown (see bottom of component).
  const llmManager = useLlmManager(undefined, liveAssistant ?? undefined);

  // Deep research toggle
  const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({
    chatSessionId: existingChatSessionId,
    assistantId: selectedAssistant?.id,
  });

  // State
  const [message, setMessage] = useState("");
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);
  const [tabReadingEnabled, setTabReadingEnabled] = useState<boolean>(false);
  const [currentTabUrl, setCurrentTabUrl] = useState<string | null>(null);
  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);

  // Document sidebar state (from store)
  const documentSidebarVisible = useDocumentSidebarVisible();
  const updateCurrentDocumentSidebarVisible = useChatSessionStore(
    (state) => state.updateCurrentDocumentSidebarVisible
  );
  const setCurrentSession = useChatSessionStore(
    (state) => state.setCurrentSession
  );
  const currentSessionId = useChatSessionStore(
    (state) => state.currentSessionId
  );

  // Memoized callback for closing document sidebar
  const handleDocumentSidebarClose = useCallback(() => {
    updateCurrentDocumentSidebarVisible(false);
  }, [updateCurrentDocumentSidebarVisible]);

  // Initialize message from URL input parameter (for Chrome extension)
  const initializedRef = useRef(false);
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    const urlParams = new URLSearchParams(window.location.search);
    const userPrompt = urlParams.get("user-prompt");
    if (userPrompt) {
      setMessage(userPrompt);
    }
  }, []);

  // Chat background from context
  const { hasBackground, appBackgroundUrl } = useAppBackground();

  // Modals
  const [showTurnOffModal, setShowTurnOffModal] = useState<boolean>(false);

  // Refs
  const inputRef = useRef<HTMLDivElement>(null);
  const chatInputBarRef = useRef<AppInputBarHandle | null>(null);
  const submitOnLoadPerformed = useRef<boolean>(false);

  // Access chat state from store
  const currentChatState = useCurrentChatState();
  const messageHistory = useCurrentMessageHistory();

  // Determine if we should show centered welcome or messages
  const hasMessages = messageHistory.length > 0;

  // Resolved assistant to use throughout the component
  const resolvedAssistant = liveAssistant ?? undefined;

  // Auto-scroll preference from user settings (matches ChatPage pattern)
  const autoScrollEnabled = user?.preferences?.auto_scroll !== false;
  const isStreaming = currentChatState === "streaming";

  // Query controller for search/chat classification (EE feature)
  const { submit: submitQuery, classification } = useQueryController();

  // Determine if retrieval (search) is enabled based on the assistant
  const retrievalEnabled = useMemo(() => {
    if (liveAssistant) {
      return personaIncludesRetrieval(liveAssistant);
    }
    return false;
  }, [liveAssistant]);

  // Check if we're in search mode
  const isSearch = classification === "search";

  // Anchor for scroll positioning (matches ChatPage pattern)
  const anchorMessage = messageHistory.at(-2) ?? messageHistory[0];
  const anchorNodeId = anchorMessage?.nodeId;
  const anchorSelector = anchorNodeId ? `#message-${anchorNodeId}` : undefined;

  useSendMessageToParent();

  // Listen for tab URL updates from the Chrome extension
  useEffect(() => {
    if (!isSidePanel) return;

    function handleExtensionMessage(event: MessageEvent) {
      // Only trust messages from the Chrome extension parent.
      // Checking the origin (chrome-extension://) prevents a non-extension
      // page that embeds NRFPage as an iframe from injecting arbitrary URLs
      // into the prompt context via TAB_URL_UPDATED.
      if (!event.origin.startsWith("chrome-extension://")) return;
      if (event.source !== window.parent) return;
      if (event.data?.type === CHROME_MESSAGE.TAB_URL_UPDATED) {
        setCurrentTabUrl(event.data.url as string);
      }
    }

    window.addEventListener("message", handleExtensionMessage);
    return () => window.removeEventListener("message", handleExtensionMessage);
  }, [isSidePanel]);

  const toggleSettings = () => {
    setSettingsOpen((prev) => !prev);
  };

  // If user toggles the "Use Onyx" switch to off, prompt a modal
  const handleUseOnyxToggle = (checked: boolean) => {
    if (!checked) {
      setShowTurnOffModal(true);
    } else {
      setUseOnyxAsNewTab(true);
      sendSetDefaultNewTabMessage(true);
    }
  };

  const confirmTurnOff = () => {
    setUseOnyxAsNewTab(false);
    setShowTurnOffModal(false);
    sendSetDefaultNewTabMessage(false);
  };

  // Reset input bar after sending
  const resetInputBar = useCallback(() => {
    setMessage("");
    setCurrentMessageFiles([]);
    chatInputBarRef.current?.reset();
  }, [setMessage, setCurrentMessageFiles]);

  // Chat controller for submitting messages
  const { onSubmit, stopGenerating, handleMessageSpecificFileUpload } =
    useChatController({
      filterManager,
      llmManager,
      availableAssistants: availableAssistants || [],
      liveAssistant,
      existingChatSessionId,
      selectedDocuments: [],
      searchParams: searchParams!,
      resetInputBar,
      setSelectedAssistantFromId,
    });

  // Chat session controller for loading sessions
  const { currentSessionFileTokenCount } = useChatSessionController({
    existingChatSessionId,
    searchParams: searchParams!,
    filterManager,
    firstMessage: undefined,
    setSelectedAssistantFromId,
    setSelectedDocuments: () => {}, // No-op: NRF doesn't support document selection
    setCurrentMessageFiles,
    chatSessionIdRef: { current: null },
    loadedIdSessionRef: { current: null },
    chatInputBarRef,
    isInitialLoad: { current: false },
    submitOnLoadPerformed,
    refreshChatSessions,
    onSubmit,
  });

  // Handle file upload
  const handleFileUpload = useCallback(
    async (acceptedFiles: File[]) => {
      handleMessageSpecificFileUpload(acceptedFiles);
    },
    [handleMessageSpecificFileUpload]
  );

  // Handle submit from AppInputBar - routes through query controller for search/chat classification
  const handleChatInputSubmit = useCallback(
    async (submittedMessage: string) => {
      if (!submittedMessage.trim()) return;

      const additionalContext =
        tabReadingEnabled && currentTabUrl
          ? `The user is currently viewing: ${currentTabUrl}. Use the open_url tool to read this page and use its content as additional context for your response.`
          : undefined;

      // If we already have messages (chat session started), always use chat mode
      // (matches AppPage behavior where existing sessions bypass classification)
      if (hasMessages) {
        resetInputBar();
        onSubmit({
          message: submittedMessage,
          currentMessageFiles: currentMessageFiles,
          deepResearch: deepResearchEnabled,
          additionalContext,
        });
        return;
      }

      // Build an onChat closure that captures additionalContext for this submission
      const onChat = (chatMessage: string) => {
        resetInputBar();
        onSubmit({
          message: chatMessage,
          currentMessageFiles: currentMessageFiles,
          deepResearch: deepResearchEnabled,
          additionalContext,
        });
      };

      // Use submitQuery which will classify the query and either:
      // - Route to search (sets classification to "search" and shows SearchUI)
      // - Route to chat (calls onChat callback)
      await submitQuery(submittedMessage, onChat);
    },
    [
      hasMessages,
      onSubmit,
      currentMessageFiles,
      deepResearchEnabled,
      resetInputBar,
      submitQuery,
      tabReadingEnabled,
      currentTabUrl,
    ]
  );

  // Handle resubmit last message on error
  const handleResubmitLastMessage = useCallback(() => {
    const lastUserMsg = messageHistory
      .slice()
      .reverse()
      .find((m) => m.type === "user");
    if (!lastUserMsg) {
      toast.error("No previously-submitted user message found.");
      return;
    }

    onSubmit({
      message: lastUserMsg.message,
      currentMessageFiles: currentMessageFiles,
      deepResearch: deepResearchEnabled,
      messageIdToResend: lastUserMsg.messageId,
    });
  }, [messageHistory, onSubmit, currentMessageFiles, deepResearchEnabled]);

  // Start a new chat session in the side panel
  const handleNewChat = useCallback(() => {
    setCurrentSession(null);
    setTabReadingEnabled(false);
    setCurrentTabUrl(null);
    resetInputBar();
    // Notify the service worker so it stops sending tab URL updates
    window.parent.postMessage(
      { type: CHROME_MESSAGE.TAB_READING_DISABLED },
      getPanelOrigin()
    );
  }, [setCurrentSession, resetInputBar]);

  const handleToggleTabReading = useCallback(() => {
    const next = !tabReadingEnabled;
    setTabReadingEnabled(next);
    if (!next) {
      setCurrentTabUrl(null);
    }
    window.parent.postMessage(
      {
        type: next
          ? CHROME_MESSAGE.TAB_READING_ENABLED
          : CHROME_MESSAGE.TAB_READING_DISABLED,
      },
      getPanelOrigin()
    );
  }, [tabReadingEnabled]);

  // Handle search result document click
  const handleSearchDocumentClick = useCallback(
    (doc: MinimalOnyxDocument) => setPresentingDocument(doc),
    []
  );

  return (
    <div
      className={cn(
        "relative w-full h-full flex flex-col overflow-hidden",
        isSidePanel
          ? "bg-background"
          : hasBackground && "bg-cover bg-center bg-fixed"
      )}
      style={
        !isSidePanel && hasBackground
          ? { backgroundImage: `url(${appBackgroundUrl})` }
          : undefined
      }
    >
      {/* Semi-transparent overlay for readability when background is set */}
      {!isSidePanel && hasBackground && (
        <div className="absolute inset-0 bg-background/80 pointer-events-none" />
      )}

      {/* Side panel header */}
      {isSidePanel && (
        <SidePanelHeader
          onNewChat={handleNewChat}
          chatSessionId={currentSessionId}
        />
      )}

      {/* Settings button */}
      {!isSidePanel && (
        <div className="absolute top-0 right-0 p-4 z-10">
          <IconButton
            icon={SvgMenu}
            onClick={toggleSettings}
            secondary
            tooltip="Open settings"
          />
        </div>
      )}

      <Dropzone onDrop={handleFileUpload} noClick>
        {({ getRootProps }) => (
          <div
            {...getRootProps()}
            className={cn(
              "flex-1 min-h-0 w-full flex flex-col items-center outline-none",
              isSidePanel && "px-3"
            )}
          >
            {/* Chat area with messages */}
            {hasMessages && resolvedAssistant && (
              <>
                {/* Fake header - pushes content below absolute settings button (non-side-panel only) */}
                {!isSidePanel && <Spacer rem={2} />}
                <ChatScrollContainer
                  sessionId="nrf-session"
                  anchorSelector={anchorSelector}
                  autoScroll={autoScrollEnabled}
                  isStreaming={isStreaming}
                  hideScrollbar={isSidePanel}
                >
                  <ChatUI
                    liveAssistant={resolvedAssistant}
                    llmManager={llmManager}
                    currentMessageFiles={currentMessageFiles}
                    setPresentingDocument={setPresentingDocument}
                    onSubmit={onSubmit}
                    onMessageSelection={() => {}}
                    stopGenerating={stopGenerating}
                    onResubmit={handleResubmitLastMessage}
                    deepResearchEnabled={deepResearchEnabled}
                    anchorNodeId={anchorNodeId}
                  />
                </ChatScrollContainer>
              </>
            )}

            {/* Welcome message - centered when no messages and not in search mode */}
            {!hasMessages && !isSearch && (
              <div className="relative w-full flex-1 flex flex-col items-center justify-end">
                <WelcomeMessage isDefaultAgent />
                <Spacer rem={1.5} />
              </div>
            )}

            {/* AppInputBar container - in normal flex flow like AppPage */}
            <div
              ref={inputRef}
              className={cn(
                "w-full flex flex-col",
                !isSidePanel &&
                  "max-w-[var(--app-page-main-content-width)] px-4"
              )}
            >
              <AppInputBar
                ref={chatInputBarRef}
                deepResearchEnabled={deepResearchEnabled}
                toggleDeepResearch={toggleDeepResearch}
                toggleDocumentSidebar={() => {}}
                filterManager={filterManager}
                llmManager={llmManager}
                removeDocs={() => {}}
                retrievalEnabled={retrievalEnabled}
                selectedDocuments={[]}
                initialMessage={message}
                stopGenerating={stopGenerating}
                onSubmit={handleChatInputSubmit}
                chatState={currentChatState}
                currentSessionFileTokenCount={currentSessionFileTokenCount}
                availableContextTokens={AVAILABLE_CONTEXT_TOKENS}
                selectedAssistant={liveAssistant ?? undefined}
                handleFileUpload={handleFileUpload}
                disabled={
                  !llmManager.isLoadingProviders && !llmManager.hasAnyProvider
                }
                {...(isSidePanel && {
                  tabReadingEnabled,
                  currentTabUrl,
                  onToggleTabReading: handleToggleTabReading,
                })}
              />
              <Spacer rem={isSidePanel ? 1 : 0.5} />
            </div>

            {/* Search results - shown when query is classified as search */}
            {isSearch && (
              <div className="flex-1 w-full max-w-[var(--app-page-main-content-width)] px-4 min-h-0 overflow-auto">
                <Spacer rem={0.75} />
                <SearchUI onDocumentClick={handleSearchDocumentClick} />
              </div>
            )}

            {/* Spacer to push content up when showing welcome message */}
            {!hasMessages && !isSearch && <div className="flex-1 w-full" />}
          </div>
        )}
      </Dropzone>

      {/* Document sidebar - shown when sources are clicked */}
      <div
        className={cn(
          "absolute right-0 top-0 h-full z-20 overflow-hidden transition-all duration-300",
          documentSidebarVisible ? "w-[25rem]" : "w-0"
        )}
      >
        <DocumentsSidebar
          setPresentingDocument={setPresentingDocument}
          modal={false}
          closeSidebar={handleDocumentSidebarClose}
          selectedDocuments={[]}
        />
      </div>

      {/* Text/document preview modal */}
      {presentingDocument && (
        <TextViewModal
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}

      {/* Modals - only show when not in side panel mode */}
      {!isSidePanel && (
        <>
          <SettingsPanel
            settingsOpen={settingsOpen}
            toggleSettings={toggleSettings}
            handleUseOnyxToggle={handleUseOnyxToggle}
          />

          <Modal open={showTurnOffModal} onOpenChange={setShowTurnOffModal}>
            <Modal.Content width="sm">
              <Modal.Header
                icon={SvgAlertTriangle}
                title="Turn off Onyx new tab page?"
                description="You'll see your browser's default new tab page instead. You can turn it back on anytime in your Onyx settings."
                onClose={() => setShowTurnOffModal(false)}
              />
              <Modal.Footer>
                <Button secondary onClick={() => setShowTurnOffModal(false)}>
                  Cancel
                </Button>
                <Button danger onClick={confirmTurnOff}>
                  Turn off
                </Button>
              </Modal.Footer>
            </Modal.Content>
          </Modal>
        </>
      )}

      {!user && (
        <Modal open onOpenChange={() => {}}>
          <Modal.Content width="sm" height="sm">
            <Modal.Header icon={SvgUser} title="Welcome to Onyx" />
            <Modal.Body>
              {authTypeMetadata.authType === AuthType.BASIC ? (
                <LoginPage
                  authUrl={null}
                  authTypeMetadata={authTypeMetadata}
                  nextUrl="/nrf"
                />
              ) : (
                <div className="flex flex-col items-center">
                  <Button
                    className="w-full"
                    secondary
                    onClick={() => {
                      if (window.top) {
                        window.top.location.href = "/auth/login";
                      } else {
                        window.location.href = "/auth/login";
                      }
                    }}
                  >
                    Log in
                  </Button>
                </div>
              )}
            </Modal.Body>
          </Modal.Content>
        </Modal>
      )}

      {user && !llmManager.isLoadingProviders && !llmManager.hasAnyProvider && (
        <Button
          className="w-full"
          secondary
          onClick={() => {
            window.location.href = "/admin/configuration/llm";
          }}
        >
          Set up an LLM.
        </Button>
      )}
    </div>
  );
}
