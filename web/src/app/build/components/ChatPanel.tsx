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
import { uploadFile } from "@/app/build/services/apiServices";
import { useLlmManager } from "@/lib/hooks";
import { BUILD_SEARCH_PARAM_NAMES } from "@/app/build/services/searchParams";
import InputBar from "@/app/build/components/InputBar";
import BuildWelcome from "@/app/build/components/BuildWelcome";
import BuildMessageList from "@/app/build/components/BuildMessageList";
import OutputPanelTab from "@/app/build/components/OutputPanelTab";
import SandboxStatusIndicator from "@/app/build/components/SandboxStatusIndicator";

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
  const consumePreProvisionedSession = useBuildSessionStore(
    (state) => state.consumePreProvisionedSession
  );
  const createNewSession = useBuildSessionStore(
    (state) => state.createNewSession
  );
  const appendMessage = useBuildSessionStore(
    (state) => state.appendMessageToCurrent
  );
  const setCurrentSession = useBuildSessionStore(
    (state) => state.setCurrentSession
  );
  const refreshSessionHistory = useBuildSessionStore(
    (state) => state.refreshSessionHistory
  );
  const nameBuildSession = useBuildSessionStore(
    (state) => state.nameBuildSession
  );
  const { streamMessage } = useBuildStreaming();
  const llmManager = useLlmManager();

  const handleSubmit = useCallback(
    async (message: string, files: BuildFile[]) => {
      if (hasSession && sessionId) {
        // Files are already uploaded when attached to existing session
        // Add user message to state
        appendMessage({
          id: `msg-${Date.now()}`,
          type: "user",
          content: message,
          timestamp: new Date(),
        });
        // Stream the response
        await streamMessage(sessionId, message);
      } else {
        // New session flow:
        // 1. Use pre-provisioned session (or fall back to creating new one)
        // 2. Upload files immediately after session creation
        // 3. Then send message to agent
        let newSessionId = await consumePreProvisionedSession();

        // Fall back to creating a new session if no pre-provisioned session
        if (!newSessionId) {
          newSessionId = await createNewSession(message);
        } else {
          // For pre-provisioned session, we need to set it as current and add user message
          setCurrentSession(newSessionId);
          appendMessage({
            id: `msg-${Date.now()}`,
            type: "user",
            content: message,
            timestamp: new Date(),
          });
          // Name the session and refresh history
          setTimeout(() => nameBuildSession(newSessionId!), 200);
          await refreshSessionHistory();
        }

        if (newSessionId) {
          // Upload files before sending message
          if (files.length > 0) {
            await Promise.all(
              files
                .filter((f) => f.file)
                .map((f) => uploadFile(newSessionId!, f.file!))
            );
          }
          router.push(
            `/build/v1?${BUILD_SEARCH_PARAM_NAMES.SESSION_ID}=${newSessionId}`
          );
          // Stream the response
          await streamMessage(newSessionId, message);
        }
      }
    },
    [
      hasSession,
      sessionId,
      appendMessage,
      streamMessage,
      consumePreProvisionedSession,
      createNewSession,
      setCurrentSession,
      refreshSessionHistory,
      nameBuildSession,
      router,
    ]
  );

  return (
    <div className="flex flex-col h-full w-full">
      {/* Chat header */}
      <div className="flex flex-row items-center justify-between pl-4 py-3">
        <SandboxStatusIndicator />
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
              sessionId={sessionId ?? undefined}
            />
          </div>
        </div>
      )}
    </div>
  );
}
