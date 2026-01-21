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
  fetchSession,
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
      const assistantMessageId = `msg-${Date.now()}-${Math.random()}-assistant`;
      appendMessageToSession(sessionId, {
        id: assistantMessageId,
        type: "assistant",
        content: "",
        timestamp: new Date(),
      });

      // Accumulator for agent message chunks (they arrive as deltas, not cumulative)
      let accumulatedMessageContent = "";

      try {
        const response = await sendMessageStream(
          sessionId,
          content,
          controller.signal
        );

        await processSSEStream(response, (packet) => {
          const packetData = packet as any;

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
            // ACP: Agent message content (arrives as deltas, not cumulative)
            case "agent_message_chunk": {
              const text = extractText(packetData.content);
              if (text) {
                // Accumulate the delta and update the message with full accumulated content
                accumulatedMessageContent += text;
                updateLastMessageInSession(
                  sessionId,
                  accumulatedMessageContent
                );
              }
              break;
            }

            // ACP: Agent's internal reasoning
            case "agent_thought_chunk":
              console.debug(
                "[Build] Thought:",
                extractText(packetData.content)
              );
              // Add as a message for the timeline
              appendMessageToSession(sessionId, {
                id: `event-thought-${Date.now()}`,
                type: "assistant",
                content: "",
                message_metadata: packetData,
                timestamp: new Date(),
              });
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
                raw_input: packetData.raw_input,
                raw_output: packetData.raw_output,
                content: packetData.content,
                startedAt: new Date(),
              };
              addToolCallToSession(sessionId, toolCall);

              // Also add as a message for the timeline
              appendMessageToSession(sessionId, {
                id: `event-${packetData.tool_call_id || Date.now()}`,
                type: "assistant",
                content: "",
                message_metadata: packetData,
                timestamp: new Date(),
              });
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

              if (toolCallId) {
                updateToolCallInSession(sessionId, toolCallId, {
                  status,
                  raw_input: packetData.raw_input,
                  raw_output: packetData.raw_output,
                  content: packetData.content,
                  ...(isFinished && { finishedAt: new Date() }),
                  ...(status === "failed" && {
                    error: packetData.error || "Tool execution failed",
                  }),
                });

                // Also add as a message for the timeline
                appendMessageToSession(sessionId, {
                  id: `event-progress-${toolCallId}-${Date.now()}`,
                  type: "assistant",
                  content: "",
                  message_metadata: packetData,
                  timestamp: new Date(),
                });
              }
              break;
            }

            // ACP: Agent's execution plan
            case "agent_plan_update":
              console.debug(
                "[Build] Plan updated:",
                packetData.entries?.length,
                "entries"
              );
              // Add as a message for the timeline
              appendMessageToSession(sessionId, {
                id: `event-plan-${Date.now()}`,
                type: "assistant",
                content: "",
                message_metadata: packetData,
                timestamp: new Date(),
              });
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

              // If it's a webapp, fetch session to get sandbox port and set webappUrl
              const isWebapp =
                newArtifact.type === "nextjs_app" ||
                newArtifact.type === "web_app";
              if (isWebapp) {
                fetchSession(sessionId)
                  .then((sessionData) => {
                    if (sessionData.sandbox?.nextjs_port) {
                      const webappUrl = `http://localhost:${sessionData.sandbox.nextjs_port}`;
                      updateSessionData(sessionId, { webappUrl });
                    }
                  })
                  .catch((err) => {
                    console.error(
                      "Failed to fetch session for webapp URL:",
                      err
                    );
                  });
              }
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
          console.error("[Streaming] Stream error:", err);
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
