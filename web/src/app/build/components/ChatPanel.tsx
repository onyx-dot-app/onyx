"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  useSession,
  useSessionId,
  useHasSession,
  useIsRunning,
  useOutputPanelOpen,
  useToggleOutputPanel,
  useBuildSessionStore,
} from "@/app/build/hooks/useBuildSessionStore";
import { useBuildStreaming } from "@/app/build/hooks/useBuildStreaming";
import { BuildFile } from "@/app/build/contexts/UploadFilesContext";
import { useLlmManager } from "@/lib/hooks";
import { BUILD_SEARCH_PARAM_NAMES } from "@/app/build/services/searchParams";
import Logo from "@/refresh-components/Logo";
import Text from "@/refresh-components/texts/Text";
import InputBar from "@/app/build/components/InputBar";
import BuildWelcome from "@/app/build/components/BuildWelcome";
import BuildMessageList from "@/app/build/components/BuildMessageList";
import OutputPanelTab from "@/app/build/components/OutputPanelTab";

/**
 * BuildChatPanel - Center panel containing the chat interface
 *
 * Handles:
 * - Welcome state (no session)
 * - Message list (when session exists)
 * - Input bar at bottom
 * - Header with output panel toggle
 */
export default function BuildChatPanel() {
  const router = useRouter();
  const outputPanelOpen = useOutputPanelOpen();
  const toggleOutputPanel = useToggleOutputPanel();
  const session = useSession();
  const sessionId = useSessionId();
  const hasSession = useHasSession();
  const isRunning = useIsRunning();
  // Access actions directly like chat does - these don't cause re-renders
  const createNewSession = useBuildSessionStore(
    (state) => state.createNewSession
  );
  const appendMessage = useBuildSessionStore(
    (state) => state.appendMessageToCurrent
  );
  const { streamMessage } = useBuildStreaming();
  const llmManager = useLlmManager();

  const handleSubmit = useCallback(
    async (message: string, _files: BuildFile[]) => {
      // TODO: Pass files to session/message when API supports it
      if (hasSession && sessionId) {
        // Add user message to state
        appendMessage({
          id: `msg-${Date.now()}`,
          role: "user",
          content: message,
          timestamp: new Date(),
        });
        // Stream the response
        await streamMessage(sessionId, message);
      } else {
        // Create new session (adds user message internally)
        const newSessionId = await createNewSession(message);
        if (newSessionId) {
          router.push(
            `/build/v1?${BUILD_SEARCH_PARAM_NAMES.SESSION_ID}=${newSessionId}`
          );
          // Stream the response after navigation
          await streamMessage(newSessionId, message);
        }
      }
    },
    [
      hasSession,
      sessionId,
      appendMessage,
      streamMessage,
      createNewSession,
      router,
    ]
  );

  return (
    <div className="flex flex-col h-full w-full">
      {/* Chat header */}
      <div className="flex flex-row items-center justify-between pl-4 py-3">
        <div className="flex flex-row items-center gap-2">
          <Logo folded size={24} />
          <Text headingH3 text05>
            Build
          </Text>
        </div>
        {/* Output panel tab in header */}
        <OutputPanelTab isOpen={outputPanelOpen} onClick={toggleOutputPanel} />
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-auto">
        {!hasSession ? (
          <BuildWelcome
            onSubmit={handleSubmit}
            isRunning={isRunning}
            llmManager={llmManager}
          />
        ) : (
          <BuildMessageList
            messages={session?.messages ?? []}
            isStreaming={isRunning}
          />
        )}
      </div>

      {/* Input bar at bottom when session exists */}
      {hasSession && (
        <div className="px-4 pb-4 pt-2">
          <div className="max-w-2xl mx-auto">
            <InputBar
              onSubmit={handleSubmit}
              isRunning={isRunning}
              placeholder="Continue the conversation..."
              llmManager={llmManager}
            />
          </div>
        </div>
      )}
    </div>
  );
}
