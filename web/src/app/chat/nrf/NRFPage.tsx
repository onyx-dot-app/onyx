"use client";
import React, { useState, useEffect, useRef, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useUser } from "@/components/user/UserProvider";
import { usePopup } from "@/components/admin/connectors/Popup";
import { AuthType } from "@/lib/constants";
import Button from "@/refresh-components/buttons/Button";
import ChatInputBar, {
  ChatInputBarHandle,
} from "@/app/chat/components/input/ChatInputBar";
import IconButton from "@/refresh-components/buttons/IconButton";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { useNightTime } from "@/lib/dateUtils";
import { useFilters, useLlmManager } from "@/lib/hooks";
import Dropzone from "react-dropzone";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { useNRFPreferences } from "@/components/context/NRFPreferencesContext";
import { SettingsPanel } from "@/app/components/nrf/SettingsPanel";
import LoginPage from "@/app/auth/login/LoginPage";
import { sendSetDefaultNewTabMessage } from "@/lib/extension/utils";
import { useAgents } from "@/hooks/useAgents";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useDeepResearchToggle } from "@/app/chat/hooks/useDeepResearchToggle";
import { useChatController } from "@/app/chat/hooks/useChatController";
import { useChatSessionController } from "@/app/chat/hooks/useChatSessionController";
import { useAssistantController } from "@/app/chat/hooks/useAssistantController";
import {
  useCurrentChatState,
  useCurrentMessageHistory,
} from "@/app/chat/stores/useChatSessionStore";
import ChatUI from "@/sections/ChatUI";
import useChatSessions from "@/hooks/useChatSessions";
import { cn } from "@/lib/utils";
import Logo from "@/refresh-components/Logo";
import { useAppSidebarContext } from "@/refresh-components/contexts/AppSidebarContext";
import { DEFAULT_CONTEXT_TOKENS } from "@/lib/constants";
import {
  SvgUser,
  SvgMenu,
  SvgExternalLink,
  SvgAlertTriangle,
} from "@opal/icons";
import { ThemePreference } from "@/lib/types";

interface NRFPageProps {
  isSidePanel?: boolean;
}

// Reserve half of the context window for the model's response output
const AVAILABLE_CONTEXT_TOKENS = Number(DEFAULT_CONTEXT_TOKENS) * 0.5;

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
    theme === ThemePreference.LIGHT
      ? defaultLightBackgroundUrl
      : defaultDarkBackgroundUrl
  );

  // Modals
  const [showTurnOffModal, setShowTurnOffModal] = useState<boolean>(false);

  // Refs
  const inputRef = useRef<HTMLDivElement>(null);
  const chatInputBarRef = useRef<ChatInputBarHandle | null>(null);
  const submitOnLoadPerformed = useRef<boolean>(false);

  // Access chat state from store
  const currentChatState = useCurrentChatState();
  const messageHistory = useCurrentMessageHistory();

  // Determine if we should show centered welcome or messages
  const hasMessages = messageHistory.length > 0;

  // Resolved assistant to use throughout the component
  const resolvedAssistant = liveAssistant ?? undefined;

  useEffect(() => {
    setBackgroundUrl(
      theme === ThemePreference.LIGHT
        ? defaultLightBackgroundUrl
        : defaultDarkBackgroundUrl
    );
  }, [theme, defaultLightBackgroundUrl, defaultDarkBackgroundUrl]);

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
      setPopup,
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

  // Handle submit from ChatInputBar
  const handleChatInputSubmit = useCallback(
    (submittedMessage: string) => {
      if (!submittedMessage.trim()) return;
      onSubmit({
        message: submittedMessage,
        currentMessageFiles: currentMessageFiles,
        deepResearch: deepResearchEnabled,
      });
    },
    [onSubmit, currentMessageFiles, deepResearchEnabled]
  );

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
      deepResearch: deepResearchEnabled,
      messageIdToResend: lastUserMsg.messageId,
    });
  }, [
    messageHistory,
    onSubmit,
    currentMessageFiles,
    deepResearchEnabled,
    setPopup,
  ]);

  const handleOpenInOnyx = () => {
    window.open(`${window.location.origin}/chat`, "_blank");
  };

  return (
    <div
      className={cn(
        "nrf-page",
        isSidePanel ? "nrf-page--side-panel" : "nrf-page--with-background"
      )}
      style={
        isSidePanel ? undefined : { backgroundImage: `url(${backgroundUrl})` }
      }
    >
      {popup}

      {/* Side panel header */}
      {isSidePanel && (
        <header className="nrf-side-panel-header">
          <div className="nrf-logo-container">
            <Logo />
          </div>
          <Button
            tertiary
            rightIcon={SvgExternalLink}
            onClick={handleOpenInOnyx}
          >
            Open in Onyx
          </Button>
        </header>
      )}

      {/* Settings button */}
      {!isSidePanel && (
        <div className="nrf-settings-button-container">
          <IconButton
            icon={SvgMenu}
            onClick={toggleSettings}
            tertiary
            tooltip="Open settings"
            className="nrf-settings-button"
          />
        </div>
      )}

      <Dropzone onDrop={handleFileUpload} noClick>
        {({ getRootProps }) => (
          <div {...getRootProps()} className="nrf-dropzone">
            {/* Chat area with messages - centered container with background */}
            {hasMessages ? (
              <div
                className={cn(
                  "nrf-chat-area",
                  isSidePanel && "nrf-chat-area--side-panel"
                )}
              >
                {/* Centered chat container with semi-transparent background */}
                <div
                  className={cn(
                    "nrf-chat-container",
                    isSidePanel && "nrf-chat-container--side-panel"
                  )}
                >
                  {/* Scrollable messages area */}
                  <div className="nrf-messages-scroll">
                    <div className="nrf-messages-content">
                      <ChatUI
                        liveAssistant={resolvedAssistant}
                        llmManager={llmManager}
                        currentMessageFiles={currentMessageFiles}
                        setPresentingDocument={() => {}}
                        onSubmit={onSubmit}
                        onMessageSelection={() => {}}
                        stopGenerating={stopGenerating}
                        handleResubmitLastMessage={handleResubmitLastMessage}
                        deepResearchEnabled={deepResearchEnabled}
                      />
                    </div>
                  </div>

                  {/* Input area - inside the container */}
                  <div
                    ref={inputRef}
                    className={cn(
                      "nrf-input-area",
                      isSidePanel && "nrf-input-area--side-panel"
                    )}
                  >
                    <ChatInputBar
                      ref={chatInputBarRef}
                      deepResearchEnabled={deepResearchEnabled}
                      toggleDeepResearch={toggleDeepResearch}
                      toggleDocumentSidebar={() => {}}
                      filterManager={filterManager}
                      llmManager={llmManager}
                      removeDocs={() => {}}
                      retrievalEnabled={false}
                      selectedDocuments={[]}
                      initialMessage={message}
                      stopGenerating={stopGenerating}
                      onSubmit={handleChatInputSubmit}
                      chatState={currentChatState}
                      currentSessionFileTokenCount={
                        currentSessionFileTokenCount
                      }
                      availableContextTokens={AVAILABLE_CONTEXT_TOKENS}
                      selectedAssistant={resolvedAssistant}
                      handleFileUpload={handleFileUpload}
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
                  "nrf-welcome",
                  isSidePanel && "nrf-welcome--side-panel"
                )}
              >
                <Text
                  headingH3
                  className={cn(
                    "nrf-welcome-heading",
                    isSidePanel || theme === "light"
                      ? "text-text-04"
                      : "text-text-light-05"
                  )}
                >
                  {isNight
                    ? "End your day with Onyx"
                    : "Start your day with Onyx"}
                </Text>

                <ChatInputBar
                  ref={chatInputBarRef}
                  deepResearchEnabled={deepResearchEnabled}
                  toggleDeepResearch={toggleDeepResearch}
                  toggleDocumentSidebar={() => {}}
                  filterManager={filterManager}
                  llmManager={llmManager}
                  removeDocs={() => {}}
                  retrievalEnabled={false}
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

          <Modal open={showTurnOffModal} onOpenChange={setShowTurnOffModal}>
            <Modal.Content mini>
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

      {!user && authTypeMetadata.authType !== AuthType.DISABLED && (
        <Modal open onOpenChange={() => {}}>
          <Modal.Content small>
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
