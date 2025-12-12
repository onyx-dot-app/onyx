"use client";
import React, {
  useState,
  useEffect,
  useRef,
  useContext,
  useMemo,
  useCallback,
} from "react";
import { useSearchParams } from "next/navigation";
import { useUser } from "@/components/user/UserProvider";
import { usePopup } from "@/components/admin/connectors/Popup";
import { AuthType } from "@/lib/constants";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import Button from "@/refresh-components/buttons/Button";
import ChatInputBar from "@/app/chat/components/input/ChatInputBar";
import { Menu, ExternalLink } from "lucide-react";
import Modal from "@/refresh-components/Modal";
import SvgUser from "@/icons/user";
import { useNightTime } from "@/lib/dateUtils";
import { useFilters, useLlmManager } from "@/lib/hooks";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import Dropzone from "react-dropzone";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { useNRFPreferences } from "@/components/context/NRFPreferencesContext";
import { SettingsPanel } from "../../components/nrf/SettingsPanel";
import LoginPage from "../../auth/login/LoginPage";
import { sendSetDefaultNewTabMessage } from "@/lib/extension/utils";
import ApiKeyModal from "@/components/llm/ApiKeyModal";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useAgents } from "@/lib/hooks/useAgents";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { useDeepResearchToggle } from "@/app/chat/hooks/useDeepResearchToggle";
import { useChatController } from "@/app/chat/hooks/useChatController";
import { useChatSessionController } from "@/app/chat/hooks/useChatSessionController";
import { useAssistantController } from "@/app/chat/hooks/useAssistantController";
import {
  useChatSessionStore,
  useChatPageLayout,
  useUncaughtError,
  useCurrentChatState,
  useCurrentMessageTree,
  useHasPerformedInitialScroll,
} from "@/app/chat/stores/useChatSessionStore";
import { MessagesDisplay } from "@/app/chat/components/MessagesDisplay";
import { useChatSessions } from "@/lib/hooks/useChatSessions";
import { useScrollonStream } from "@/app/chat/services/lib";
import { cn } from "@/lib/utils";
import Logo from "@/refresh-components/Logo";
import useScreenSize from "@/hooks/useScreenSize";
import TextView from "@/components/chat/TextView";
import { useAppSidebarContext } from "@/refresh-components/contexts/AppSidebarContext";
import DEFAULT_CONTEXT_TOKENS from "@/app/chat/components/ChatPage";

interface NRFPageProps {
  isSidePanel?: boolean;
}

export default function NRFPage({ isSidePanel = false }: NRFPageProps) {
  const {
    theme,
    defaultLightBackgroundUrl,
    defaultDarkBackgroundUrl,
    setUseOnyxAsNewTab,
  } = useNRFPreferences();

  const searchParams = useSearchParams();
  const filterManager = useFilters();
  const { isNight } = useNightTime();
  const { user, authTypeMetadata } = useUser();
  const { llmProviders } = useLLMProviders();
  const settings = useContext(SettingsContext);
  const { height: screenHeight } = useScreenSize();
  const { setFolded } = useAppSidebarContext();

  const { popup, setPopup } = usePopup();

  // Hide sidebar when in side panel mode
  useEffect(() => {
    if (isSidePanel) {
      setFolded(true);
    }
  }, [isSidePanel, setFolded]);

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

  // Show popup if any files failed
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

  // Assistant controller
  const { selectedAssistant, setSelectedAssistantFromId, liveAssistant } =
    useAssistantController({
      selectedChatSession: undefined,
      onAssistantSelect: () => {},
    });

  // LLM manager for model selection
  const llmManager = useLlmManager(undefined, liveAssistant ?? undefined);

  // Deep research toggle
  const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({
    chatSessionId: existingChatSessionId,
    assistantId: selectedAssistant?.id,
  });

  // State
  const [message, setMessage] = useState("");
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);

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

  const [backgroundUrl, setBackgroundUrl] = useState<string>(
    theme === "light" ? defaultLightBackgroundUrl : defaultDarkBackgroundUrl
  );
  const [selectedDocuments, setSelectedDocuments] = useState<OnyxDocument[]>(
    []
  );
  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);

  // Modals
  const [showTurnOffModal, setShowTurnOffModal] = useState<boolean>(false);
  const [showLoginModal, setShowLoginModal] = useState<boolean>(!user);

  // Refs for scrolling
  const scrollableDivRef = useRef<HTMLDivElement>(null);
  const lastMessageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLDivElement>(null);
  const endDivRef = useRef<HTMLDivElement>(null);
  const endPaddingRef = useRef<HTMLDivElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  const waitForScrollRef = useRef(false);
  const scrollDist = useRef<number>(0);
  const scrollInitialized = useRef(false);
  const isInitialLoad = useRef(true);
  const chatSessionIdRef = useRef<string | null>(existingChatSessionId);
  const loadedIdSessionRef = useRef<string | null>(existingChatSessionId);
  const submitOnLoadPerformed = useRef<boolean>(false);

  // Access chat state from store
  const currentChatState = useCurrentChatState();
  const chatSessionId = useChatSessionStore((state) => state.currentSessionId);
  const uncaughtError = useUncaughtError();
  const completeMessageTree = useCurrentMessageTree();
  const hasPerformedInitialScroll = useHasPerformedInitialScroll();
  const updateHasPerformedInitialScroll = useChatSessionStore(
    (state) => state.updateHasPerformedInitialScroll
  );
  const { showCenteredInput, loadingError, messageHistory } =
    useChatPageLayout();

  // Determine if we should show centered welcome or messages
  const hasMessages = messageHistory.length > 0;

  useEffect(() => {
    setBackgroundUrl(
      theme === "light" ? defaultLightBackgroundUrl : defaultDarkBackgroundUrl
    );
  }, [theme, defaultLightBackgroundUrl, defaultDarkBackgroundUrl]);

  // Set reduced bottom padding for NRF (input is inside container)
  useEffect(() => {
    if (hasMessages && endPaddingRef.current) {
      endPaddingRef.current.style.height = `16px`;
    }
  }, [hasMessages]);

  useSendMessageToParent();

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

  // Scroll to bottom
  const clientScrollToBottom = useCallback(
    (fast?: boolean) => {
      waitForScrollRef.current = true;

      setTimeout(() => {
        if (!endDivRef.current || !scrollableDivRef.current) {
          return;
        }

        const rect = endDivRef.current.getBoundingClientRect();
        const isVisible = rect.top >= 0 && rect.bottom <= window.innerHeight;

        if (isVisible) return;

        endDivRef.current.scrollIntoView({
          behavior: fast ? "auto" : "smooth",
        });

        if (chatSessionIdRef.current) {
          updateHasPerformedInitialScroll(chatSessionIdRef.current, true);
        }
      }, 50);

      setTimeout(() => {
        waitForScrollRef.current = false;
      }, 1500);
    },
    [updateHasPerformedInitialScroll]
  );

  // Reset input bar after sending
  const resetInputBar = useCallback(() => {
    setMessage("");
    setCurrentMessageFiles([]);
    if (endPaddingRef.current) {
      // Reduced padding for NRF since input is inside the container
      endPaddingRef.current.style.height = `16px`;
    }
  }, [setMessage, setCurrentMessageFiles]);

  // Chat controller for submitting messages
  const { onSubmit, stopGenerating, handleMessageSpecificFileUpload } =
    useChatController({
      filterManager,
      llmManager,
      availableAssistants: availableAssistants || [],
      liveAssistant,
      existingChatSessionId,
      selectedDocuments,
      searchParams: searchParams!,
      setPopup,
      clientScrollToBottom,
      resetInputBar,
      setSelectedAssistantFromId,
    });

  // Chat session controller for loading sessions
  const { onMessageSelection, currentSessionFileTokenCount } =
    useChatSessionController({
      existingChatSessionId,
      searchParams: searchParams!,
      filterManager,
      firstMessage: undefined,
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

  // Auto scroll on stream
  const autoScrollEnabled = user?.preferences?.auto_scroll ?? false;
  const debounceNumber = 100;

  useScrollonStream({
    chatState: currentChatState,
    scrollableDivRef,
    scrollDist,
    endDivRef,
    debounceNumber,
    mobile: settings?.isMobile,
    enableAutoScroll: autoScrollEnabled,
  });

  // Container height for messages
  const getContainerHeight = useMemo(() => {
    return () => {
      if (autoScrollEnabled) return undefined;
      if (screenHeight < 600) return "40vh";
      if (screenHeight < 1200) return "50vh";
      return "60vh";
    };
  }, [autoScrollEnabled, screenHeight]);

  // Handle file upload
  const handleFileUpload = useCallback(
    async (acceptedFiles: File[]) => {
      handleMessageSpecificFileUpload(acceptedFiles);
    },
    [handleMessageSpecificFileUpload]
  );

  // Handle submit from ChatInputBar
  const handleChatInputSubmit = useCallback(() => {
    if (!message.trim()) return;
    onSubmit({
      message: message,
      currentMessageFiles: currentMessageFiles,
      useAgentSearch: deepResearchEnabled,
    });
  }, [message, onSubmit, currentMessageFiles, deepResearchEnabled]);

  // Handle resubmit last message on error
  const handleResubmitLastMessage = useCallback(() => {
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

    onSubmit({
      message: lastUserMsg.message,
      currentMessageFiles: currentMessageFiles,
      useAgentSearch: deepResearchEnabled,
      messageIdToResend: lastUserMsg.messageId,
    });
  }, [
    messageHistory,
    onSubmit,
    currentMessageFiles,
    deepResearchEnabled,
    setPopup,
  ]);

  const toggleDocumentSidebar = () => {
    // No-op for NRF page - document sidebar not applicable
  };

  const handleOpenInOnyx = () => {
    window.open(`${window.location.origin}/chat`, "_blank");
  };

  return (
    <div
      className={cn(
        "relative w-full h-full flex flex-col min-h-screen overflow-hidden",
        isSidePanel
          ? "bg-background"
          : "bg-cover bg-center bg-no-repeat transition-[background-image] duration-150 ease-in-out"
      )}
      style={
        isSidePanel ? undefined : { backgroundImage: `url(${backgroundUrl})` }
      }
    >
      {popup}

      {/* Side panel header */}
      {isSidePanel && (
        <header className="flex items-center justify-between px-4 py-3 border-b border-border bg-background">
          <div className="flex items-center gap-2">
            <Logo />
          </div>
          <button
            onClick={handleOpenInOnyx}
            className="flex items-center gap-1.5 text-sm text-text-600 hover:text-text-900 transition-colors"
          >
            Open in Onyx
            <ExternalLink size={14} />
          </button>
        </header>
      )}

      {/* Settings button */}
      {!isSidePanel && (
        <div className="absolute top-0 right-0 p-4 z-10">
          <button
            aria-label="Open settings"
            onClick={toggleSettings}
            className="bg-white/70 dark:bg-neutral-500/70 backdrop-blur-md rounded-full p-2.5 cursor-pointer hover:bg-white/80 dark:hover:bg-neutral-700/80 transition-colors duration-200 shadow-lg"
          >
            <Menu
              size={12}
              className={theme === "light" ? "text-text-900" : "text-white"}
            />
          </button>
        </div>
      )}

      {/* Text view modal for viewing documents */}
      {presentingDocument && (
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}

      <Dropzone onDrop={handleFileUpload} noClick>
        {({ getRootProps }) => (
          <div
            {...getRootProps()}
            className="flex-1 flex flex-col overflow-hidden"
          >
            {/* Chat area with messages - centered container with background */}
            {hasMessages ? (
              <div
                className={cn(
                  "flex-1 flex justify-center min-h-0",
                  isSidePanel ? "p-0" : "py-4 px-4 md:px-8 lg:px-16"
                )}
              >
                {/* Centered chat container with semi-transparent background */}
                <div
                  className={cn(
                    "flex flex-col w-full max-h-full overflow-hidden",
                    isSidePanel
                      ? "max-w-full"
                      : "max-w-4xl bg-white/60 dark:bg-neutral-900/60 backdrop-blur-md rounded-2xl shadow-lg"
                  )}
                >
                  {/* Scrollable messages area */}
                  <div
                    ref={scrollableDivRef}
                    onScroll={() => {
                      const scrollDistance =
                        (endDivRef?.current?.getBoundingClientRect()?.top ??
                          0) -
                        (inputRef?.current?.getBoundingClientRect()?.top ?? 0);
                      scrollDist.current = scrollDistance;
                    }}
                    className="flex-1 w-full flex flex-col default-scrollbar overflow-y-auto overflow-x-hidden relative"
                  >
                    <div className="relative w-full px-4">
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
                        endPaddingRef={endPaddingRef}
                        endDivRef={endDivRef}
                        hasPerformedInitialScroll={hasPerformedInitialScroll}
                        chatSessionId={chatSessionId}
                        enterpriseSettings={settings?.enterpriseSettings}
                      />
                    </div>
                  </div>

                  {/* Input area - inside the container */}
                  <div
                    ref={inputRef}
                    className={cn(
                      "p-4 border-t",
                      isSidePanel
                        ? "border-border"
                        : "border-white/20 dark:border-neutral-700/50"
                    )}
                  >
                    <ChatInputBar
                      deepResearchEnabled={deepResearchEnabled}
                      toggleDeepResearch={toggleDeepResearch}
                      toggleDocumentSidebar={toggleDocumentSidebar}
                      filterManager={filterManager}
                      llmManager={llmManager}
                      removeDocs={() => setSelectedDocuments([])}
                      retrievalEnabled={false}
                      selectedDocuments={selectedDocuments}
                      message={message}
                      setMessage={setMessage}
                      stopGenerating={stopGenerating}
                      onSubmit={handleChatInputSubmit}
                      chatState={currentChatState}
                      currentSessionFileTokenCount={
                        currentSessionFileTokenCount
                      }
                      availableContextTokens={
                        Number(DEFAULT_CONTEXT_TOKENS) * 0.5
                      }
                      selectedAssistant={liveAssistant ?? undefined}
                      handleFileUpload={handleFileUpload}
                      textAreaRef={textAreaRef}
                      disabled={
                        !llmManager.isLoadingProviders &&
                        !llmManager.hasAnyProvider
                      }
                    />
                  </div>
                </div>
              </div>
            ) : (
              /* Welcome/Input area - centered when no messages */
              <div
                ref={inputRef}
                className={cn(
                  "text-center",
                  isSidePanel
                    ? "flex-1 flex flex-col justify-center px-4"
                    : "absolute top-[40%] left-1/2 -translate-x-1/2 -translate-y-1/2 w-[90%] lg:max-w-3xl"
                )}
              >
                <h1
                  className={cn(
                    "pl-2 text-xl text-left w-full mb-4",
                    isSidePanel
                      ? "text-text-800"
                      : theme === "light"
                        ? "text-text-800"
                        : "text-white"
                  )}
                >
                  {isNight
                    ? "End your day with Onyx"
                    : "Start your day with Onyx"}
                </h1>

                <ChatInputBar
                  deepResearchEnabled={deepResearchEnabled}
                  toggleDeepResearch={toggleDeepResearch}
                  toggleDocumentSidebar={toggleDocumentSidebar}
                  filterManager={filterManager}
                  llmManager={llmManager}
                  removeDocs={() => setSelectedDocuments([])}
                  retrievalEnabled={false}
                  selectedDocuments={selectedDocuments}
                  message={message}
                  setMessage={setMessage}
                  stopGenerating={stopGenerating}
                  onSubmit={handleChatInputSubmit}
                  chatState={currentChatState}
                  currentSessionFileTokenCount={currentSessionFileTokenCount}
                  availableContextTokens={Number(DEFAULT_CONTEXT_TOKENS) * 0.5}
                  selectedAssistant={liveAssistant ?? undefined}
                  handleFileUpload={handleFileUpload}
                  textAreaRef={textAreaRef}
                  disabled={
                    !llmManager.isLoadingProviders && !llmManager.hasAnyProvider
                  }
                />
              </div>
            )}
          </div>
        )}
      </Dropzone>

      {/* Modals - only show when not in side panel mode */}
      {!isSidePanel && (
        <>
          <SettingsPanel
            settingsOpen={settingsOpen}
            toggleSettings={toggleSettings}
            handleUseOnyxToggle={handleUseOnyxToggle}
          />

          <Dialog open={showTurnOffModal} onOpenChange={setShowTurnOffModal}>
            <DialogContent className="w-fit max-w-[95%]">
              <DialogHeader>
                <DialogTitle>Turn off Onyx new tab page?</DialogTitle>
                <DialogDescription>
                  You&apos;ll see your browser&apos;s default new tab page
                  instead.
                  <br />
                  You can turn it back on anytime in your Onyx settings.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter className="flex gap-2 justify-center">
                <Button secondary onClick={() => setShowTurnOffModal(false)}>
                  Cancel
                </Button>
                <Button danger onClick={confirmTurnOff}>
                  Turn off
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      )}

      {!user &&
      authTypeMetadata.authType !== AuthType.DISABLED &&
      showLoginModal ? (
        <Modal open onOpenChange={() => setShowLoginModal(false)}>
          <Modal.Content small>
            <Modal.Header
              icon={SvgUser}
              title="Welcome to Onyx"
              onClose={() => setShowLoginModal(false)}
            />
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
      ) : (
        (!llmProviders || llmProviders.length === 0) && (
          <ApiKeyModal setPopup={setPopup} />
        )
      )}
    </div>
  );
}
