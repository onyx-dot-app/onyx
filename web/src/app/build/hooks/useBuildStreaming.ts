"use client";

import { useCallback, useMemo } from "react";

import {
  Artifact,
  OutputDeltaPacket,
  ArtifactCreatedPacket,
  ErrorPacket,
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

      // Set status to running
      updateSessionData(sessionId, { status: "running" });

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
          switch (packet.type) {
            case "output_delta":
              assistantContent += (packet as OutputDeltaPacket).content;
              updateLastMessageInSession(sessionId, assistantContent);
              break;

            case "artifact_created": {
              const artPacket = packet as ArtifactCreatedPacket;
              const newArtifact: Artifact = {
                id: artPacket.artifact.id,
                session_id: sessionId,
                type: artPacket.artifact.type,
                name: artPacket.artifact.name,
                path: artPacket.artifact.path,
                preview_url: artPacket.artifact.preview_url,
                created_at: new Date(),
                updated_at: new Date(),
              };
              addArtifactToSession(sessionId, newArtifact);
              break;
            }

            case "done":
              updateSessionData(sessionId, { status: "completed" });
              break;

            case "error": {
              const errPacket = packet as ErrorPacket;
              updateSessionData(sessionId, {
                status: "failed",
                error: errPacket.message,
              });
              break;
            }
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
