"use client";

import { useCallback, useMemo } from "react";

import {
  Artifact,
  ArtifactType,
  ArtifactCreatedPacket,
  ErrorPacket,
  ToolCall,
  ToolCallStatus,
} from "@/app/build/services/buildStreamingModels";

import {
  sendMessageStream,
  processSSEStream,
} from "@/app/build/services/apiServices";

import { useBuildSessionStore } from "@/app/build/hooks/useBuildSessionStore";

/**
 * Hook for handling message streaming in build sessions.
 * Uses session-specific actions to avoid race conditions with currentSessionId.
 */
export function useBuildStreaming() {
  // Store actions - use session-specific methods to avoid race conditions
  // when currentSessionId changes during navigation
  const appendMessageToSession = useBuildSessionStore(
    (state) => state.appendMessageToSession
  );
  const updateLastMessageInSession = useBuildSessionStore(
    (state) => state.updateLastMessageInSession
  );
  const addArtifactToSession = useBuildSessionStore(
    (state) => state.addArtifactToSession
  );
  const addToolCallToSession = useBuildSessionStore(
    (state) => state.addToolCallToSession
  );
  const updateToolCallInSession = useBuildSessionStore(
    (state) => state.updateToolCallInSession
  );
  const clearToolCallsInSession = useBuildSessionStore(
    (state) => state.clearToolCallsInSession
  );
  const setAbortController = useBuildSessionStore(
    (state) => state.setAbortController
  );
  const abortCurrentSession = useBuildSessionStore(
    (state) => state.abortCurrentSession
  );
  const updateSessionData = useBuildSessionStore(
    (state) => state.updateSessionData
  );

  /**
   * Stream a message to the given session and process the SSE response.
   * Updates store state as packets arrive.
   */
  const streamMessage = useCallback(
    async (sessionId: string, content: string): Promise<void> => {
      // Access sessions via getState() to avoid dependency on sessions Map reference
      const currentState = useBuildSessionStore.getState();
      const existingSession = currentState.sessions.get(sessionId);
      if (existingSession?.abortController) {
        existingSession.abortController.abort();
      }

      // Create new abort controller for this stream
      const controller = new AbortController();
      setAbortController(sessionId, controller);

      // Set status to running and clear previous tool calls
      updateSessionData(sessionId, { status: "running" });
      clearToolCallsInSession(sessionId);

      // Add placeholder assistant message using session-specific method
      // to avoid race condition when currentSessionId changes during navigation
      appendMessageToSession(sessionId, {
        id: `msg-${Date.now()}-assistant`,
        role: "assistant",
        content: "",
        timestamp: new Date(),
      });

      try {
        const response = await sendMessageStream(
          sessionId,
          content,
          controller.signal
        );

        let assistantContent = "";

        await processSSEStream(response, (packet) => {
          const packetData = packet as any;

          // Log all incoming packets for debugging
          console.log("[Build] SSE Packet received:", packet.type, packet);

          // Helper to extract text from ACP content structure
          const extractText = (content: any): string => {
            if (!content) return "";
            if (content.type === "text" && content.text) return content.text;
            if (Array.isArray(content)) {
              return content
                .filter((c: any) => c.type === "text" && c.text)
                .map((c: any) => c.text)
                .join("");
            }
            return "";
          };

          switch (packet.type) {
            // ACP: Agent message content
            case "agent_message_chunk": {
              const text = extractText(packetData.content);
              if (text) {
                assistantContent += text;
                updateLastMessageInSession(sessionId, assistantContent);
              }
              break;
            }

            // ACP: Agent's internal reasoning
            case "agent_thought_chunk":
              console.debug(
                "[Build] Thought:",
                extractText(packetData.content)
              );
              break;

            // ACP: Tool invocation started
            case "tool_call_start": {
              const toolCall: ToolCall = {
                id: packetData.tool_call_id || `tc-${Date.now()}`,
                kind: packetData.kind || "other",
                name: packetData.title || packetData.kind || "unknown",
                title:
                  packetData.title || `Running ${packetData.kind || "tool"}...`,
                status: "in_progress",
                input: packetData.input,
                startedAt: new Date(),
              };
              console.log("[Build] Tool started:", toolCall);
              addToolCallToSession(sessionId, toolCall);
              break;
            }

            // ACP: Tool execution progress
            case "tool_call_progress": {
              const toolCallId = packetData.tool_call_id;
              const status = packetData.status as ToolCallStatus;
              const isFinished =
                status === "completed" ||
                status === "failed" ||
                status === "cancelled";

              console.log("[Build] Tool progress:", packetData.kind, status);

              if (toolCallId) {
                updateToolCallInSession(sessionId, toolCallId, {
                  status,
                  ...(isFinished && { finishedAt: new Date() }),
                  ...(status === "failed" && {
                    error: packetData.error || "Tool execution failed",
                  }),
                });
              }
              break;
            }

            // ACP: Agent's execution plan
            case "agent_plan_update":
              console.debug(
                "[Build] Plan updated:",
                packetData.plan?.entries?.length,
                "entries"
              );
              break;

            // ACP: Agent mode change
            case "current_mode_update":
              console.debug(
                "[Build] Mode updated:",
                packetData.current_mode_id
              );
              break;

            // File operations
            case "file_write":
              console.debug("[Build] File written:", packet);
              break;

            // Artifacts - add to session
            case "artifact_created": {
              const artPacket = packet as ArtifactCreatedPacket;
              const newArtifact: Artifact = {
                id: artPacket.artifact.id,
                session_id: sessionId,
                type: artPacket.artifact.type as ArtifactType,
                name: artPacket.artifact.name,
                path: artPacket.artifact.path,
                preview_url: artPacket.artifact.preview_url || null,
                created_at: new Date(),
                updated_at: new Date(),
              };
              addArtifactToSession(sessionId, newArtifact);
              break;
            }

            // ACP: Agent finished
            case "prompt_response":
              updateSessionData(sessionId, { status: "completed" });
              break;

            // Error
            case "error": {
              const errPacket = packet as ErrorPacket;
              updateSessionData(sessionId, {
                status: "failed",
                error: errPacket.message || packetData.message,
              });
              break;
            }

            // Unknown packet types - log for debugging
            default:
              console.debug(
                "[Build] Unhandled packet type:",
                packet.type,
                packet
              );
              break;
          }
        });
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          console.error("Stream error:", err);
          updateSessionData(sessionId, {
            status: "failed",
            error: (err as Error).message,
          });
        }
      } finally {
        // Create a fresh abort controller for future use
        setAbortController(sessionId, new AbortController());
      }
    },
    [
      setAbortController,
      updateSessionData,
      appendMessageToSession,
      updateLastMessageInSession,
      addArtifactToSession,
      addToolCallToSession,
      updateToolCallInSession,
      clearToolCallsInSession,
    ]
  );

  // Memoize the return object to ensure stable reference
  return useMemo(
    () => ({
      streamMessage,
      abortStream: abortCurrentSession,
    }),
    [streamMessage, abortCurrentSession]
  );
}
