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
  useIsPreProvisioning,
} from "@/app/build/hooks/useBuildSessionStore";
import { useBuildStreaming } from "@/app/build/hooks/useBuildStreaming";
import { BuildFile } from "@/app/build/contexts/UploadFilesContext";
import { uploadFile } from "@/app/build/services/apiServices";
import { useLlmManager } from "@/lib/hooks";
import { BUILD_SEARCH_PARAM_NAMES } from "@/app/build/services/searchParams";
import { usePopup } from "@/components/admin/connectors/Popup";
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
  const { popup, setPopup } = usePopup();
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
  const createSession = useBuildSessionStore((state) => state.createSession);
  const appendMessageToCurrent = useBuildSessionStore(
    (state) => state.appendMessageToCurrent
  );
  const appendMessageToSession = useBuildSessionStore(
    (state) => state.appendMessageToSession
  );
  const refreshSessionHistory = useBuildSessionStore(
    (state) => state.refreshSessionHistory
  );
  const nameBuildSession = useBuildSessionStore(
    (state) => state.nameBuildSession
  );
  const { streamMessage } = useBuildStreaming();
  const isPreProvisioning = useIsPreProvisioning();
  const llmManager = useLlmManager();

  const handleSubmit = useCallback(
    async (message: string, files: BuildFile[]) => {
      console.log("[ChatPanel] handleSubmit called", {
        hasSession,
        sessionId,
        isRunning,
        messageLength: message.length,
        filesCount: files.length,
      });

      if (hasSession && sessionId) {
        // Existing session flow
        console.log("[ChatPanel] Existing session flow");
        // Check if response is still streaming - show toast like main chat does
        if (isRunning) {
          console.log("[ChatPanel] Already running, showing popup");
          setPopup({
            message: "Please wait for the current operation to complete.",
            type: "error",
          });
          return;
        }

        // Add user message to state
        console.log("[ChatPanel] Adding user message to current session");
        appendMessageToCurrent({
          id: `msg-${Date.now()}`,
          type: "user",
          content: message,
          timestamp: new Date(),
        });
        // Stream the response
        console.log("[ChatPanel] Starting streamMessage for existing session");
        await streamMessage(sessionId, message);
        console.log("[ChatPanel] streamMessage completed");
      } else {
        // New session flow - get pre-provisioned session or fall back to creating new one
        console.log(
          "[ChatPanel] New session flow - attempting to consume pre-provisioned session"
        );
        const newSessionId = await consumePreProvisionedSession();
        console.log(
          "[ChatPanel] consumePreProvisionedSession returned:",
          newSessionId
        );

        if (!newSessionId) {
          // Fallback: createNewSession handles everything including navigation
          console.log(
            "[ChatPanel] No pre-provisioned session, falling back to createNewSession"
          );
          const fallbackSessionId = await createNewSession(message);
          console.log(
            "[ChatPanel] createNewSession returned:",
            fallbackSessionId
          );
          if (fallbackSessionId) {
            if (files.length > 0) {
              console.log("[ChatPanel] Uploading", files.length, "files");
              await Promise.all(
                files
                  .filter((f) => f.file)
                  .map((f) => uploadFile(fallbackSessionId, f.file!))
              );
              console.log("[ChatPanel] File upload complete");
            }
            console.log(
              "[ChatPanel] Starting streamMessage for new session (fallback)"
            );
            await streamMessage(fallbackSessionId, message);
            console.log("[ChatPanel] streamMessage completed (fallback)");
          }
        } else {
          // Pre-provisioned session flow:
          // The backend session already exists (created during pre-provisioning).
          // Here we initialize the LOCAL Zustand store entry with the right state.
          console.log(
            "[ChatPanel] Using pre-provisioned session:",
            newSessionId
          );
          const userMessage = {
            id: `msg-${Date.now()}`,
            type: "user" as const,
            content: message,
            timestamp: new Date(),
          };
          // Initialize local state (NOT an API call - backend session already exists)
          // - isLoaded: true prevents loadSession from overwriting with server data
          // - status: "running" disables input immediately
          // Note: sandbox status indicator will optimistically show "running" for sessions
          // without sandbox info (see deriveSandboxStatus)
          console.log("[ChatPanel] Creating local session state");
          createSession(newSessionId, {
            isLoaded: true,
            messages: [userMessage],
            status: "running",
          });

          // 2. Upload files before navigation
          if (files.length > 0) {
            console.log(
              "[ChatPanel] Uploading",
              files.length,
              "files (pre-provisioned flow)"
            );
            await Promise.all(
              files
                .filter((f) => f.file)
                .map((f) => uploadFile(newSessionId, f.file!))
            );
            console.log(
              "[ChatPanel] File upload complete (pre-provisioned flow)"
            );
          }

          // 3. Navigate to URL - session controller will set currentSessionId
          console.log("[ChatPanel] Navigating to session URL");
          router.push(
            `/build/v1?${BUILD_SEARCH_PARAM_NAMES.SESSION_ID}=${newSessionId}`
          );

          // 4. Name the session and refresh history
          console.log(
            "[ChatPanel] Scheduling session naming and refreshing history"
          );
          setTimeout(() => nameBuildSession(newSessionId), 200);
          await refreshSessionHistory();

          // 5. Stream the response (uses session ID directly, not currentSessionId)
          console.log(
            "[ChatPanel] Starting streamMessage for pre-provisioned session"
          );
          await streamMessage(newSessionId, message);
          console.log("[ChatPanel] streamMessage completed (pre-provisioned)");
        }
      }
    },
    [
      hasSession,
      sessionId,
      isRunning,
      setPopup,
      appendMessageToCurrent,
      streamMessage,
      consumePreProvisionedSession,
      createNewSession,
      createSession,
      appendMessageToSession,
      refreshSessionHistory,
      nameBuildSession,
      router,
    ]
  );

  return (
    <div className="flex flex-col h-full w-full">
      {popup}
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
            sandboxInitializing={isPreProvisioning}
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
