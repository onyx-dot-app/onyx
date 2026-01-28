"use client";

import { useCallback, useMemo } from "react";

import {
  Artifact,
  ArtifactType,
  SessionErrorCode,
} from "@/app/craft/types/streamingTypes";

import {
  sendMessageStream,
  processSSEStream,
  fetchSession,
  generateFollowupSuggestions,
  RateLimitError,
} from "@/app/craft/services/apiServices";

import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { StreamItem } from "@/app/craft/types/displayTypes";

import { genId } from "@/app/craft/utils/streamItemHelpers";
import { parsePacket } from "@/app/craft/utils/parsePacket";

/**
 * Hook for handling message streaming in build sessions.
 *
 * Uses a simple FIFO approach:
 * - Stream items are appended in chronological order as packets arrive
 * - Text/thinking chunks are merged when consecutive
 * - Tool calls are interleaved with text in the exact order they arrive
 */
export function useBuildStreaming() {
  const appendMessageToSession = useBuildSessionStore(
    (state) => state.appendMessageToSession
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

  // Stream item actions
  const appendStreamItem = useBuildSessionStore(
    (state) => state.appendStreamItem
  );
  const updateLastStreamingText = useBuildSessionStore(
    (state) => state.updateLastStreamingText
  );
  const updateLastStreamingThinking = useBuildSessionStore(
    (state) => state.updateLastStreamingThinking
  );
  const updateToolCallStreamItem = useBuildSessionStore(
    (state) => state.updateToolCallStreamItem
  );
  const upsertTodoListStreamItem = useBuildSessionStore(
    (state) => state.upsertTodoListStreamItem
  );
  const clearStreamItems = useBuildSessionStore(
    (state) => state.clearStreamItems
  );
  const triggerWebappRefresh = useBuildSessionStore(
    (state) => state.triggerWebappRefresh
  );
  const triggerFilesRefresh = useBuildSessionStore(
    (state) => state.triggerFilesRefresh
  );
  const openMarkdownPreview = useBuildSessionStore(
    (state) => state.openMarkdownPreview
  );
  const setFollowupSuggestions = useBuildSessionStore(
    (state) => state.setFollowupSuggestions
  );
  const setSuggestionsLoading = useBuildSessionStore(
    (state) => state.setSuggestionsLoading
  );

  // ── Output file detector registry ──────────────────────────────────────
  // Ordered by priority — first match wins.
  // To add a new output type, add an entry here + a store action.
  const OUTPUT_FILE_DETECTORS = useMemo(
    () => [
      {
        match: (fp: string, k: string) =>
          (k === "edit" || k === "write") &&
          (fp.includes("/web/") || fp.startsWith("web/")),
        onDetect: (sid: string) => triggerWebappRefresh(sid),
      },
      {
        match: (fp: string, k: string) =>
          (k === "edit" || k === "write") &&
          fp.endsWith(".md") &&
          (fp.includes("/outputs/") || fp.startsWith("outputs/")),
        onDetect: (sid: string, fp: string) => {
          openMarkdownPreview(sid, fp);
          triggerFilesRefresh(sid);
        },
      },
      {
        match: (fp: string, k: string) =>
          (k === "edit" || k === "write") &&
          (fp.includes("/outputs/") || fp.startsWith("outputs/")),
        onDetect: (sid: string) => triggerFilesRefresh(sid),
      },
    ],
    [triggerWebappRefresh, triggerFilesRefresh, openMarkdownPreview]
  );

  /**
   * Stream a message to the given session and process the SSE response.
   * Populates streamItems in FIFO order as packets arrive.
   */
  const streamMessage = useCallback(
    async (sessionId: string, content: string): Promise<void> => {
      const currentState = useBuildSessionStore.getState();
      const existingSession = currentState.sessions.get(sessionId);

      if (existingSession?.abortController) {
        existingSession.abortController.abort();
      }

      const controller = new AbortController();
      setAbortController(sessionId, controller);

      // Set status to running and clear previous stream items
      updateSessionData(sessionId, { status: "running" });
      clearStreamItems(sessionId);

      // Track accumulated content for streaming text/thinking
      let accumulatedText = "";
      let accumulatedThinking = "";
      let lastItemType: "text" | "thinking" | "tool" | null = null;

      // Helper to finalize any streaming item before switching types
      const finalizeStreaming = () => {
        const session = useBuildSessionStore.getState().sessions.get(sessionId);
        if (!session) return;

        const items = session.streamItems;
        const lastItem = items[items.length - 1];
        if (lastItem) {
          if (lastItem.type === "text" && lastItem.isStreaming) {
            useBuildSessionStore
              .getState()
              .updateStreamItem(sessionId, lastItem.id, { isStreaming: false });
          } else if (lastItem.type === "thinking" && lastItem.isStreaming) {
            useBuildSessionStore
              .getState()
              .updateStreamItem(sessionId, lastItem.id, { isStreaming: false });
          }
        }
      };

      try {
        const response = await sendMessageStream(
          sessionId,
          content,
          controller.signal
        );

        await processSSEStream(response, (rawPacket) => {
          const parsed = parsePacket(rawPacket);

          switch (parsed.type) {
            // Agent message content - accumulate and update/create text item
            case "text_chunk": {
              if (!parsed.text) break;

              accumulatedText += parsed.text;

              if (lastItemType === "text") {
                updateLastStreamingText(sessionId, accumulatedText);
              } else {
                finalizeStreaming();
                accumulatedText = parsed.text;
                const item: StreamItem = {
                  type: "text",
                  id: genId("text"),
                  content: parsed.text,
                  isStreaming: true,
                };
                appendStreamItem(sessionId, item);
                lastItemType = "text";
              }
              break;
            }

            // Agent thinking - accumulate and update/create thinking item
            case "thinking_chunk": {
              if (!parsed.text) break;

              accumulatedThinking += parsed.text;

              if (lastItemType === "thinking") {
                updateLastStreamingThinking(sessionId, accumulatedThinking);
              } else {
                finalizeStreaming();
                accumulatedThinking = parsed.text;
                const item: StreamItem = {
                  type: "thinking",
                  id: genId("thinking"),
                  content: parsed.text,
                  isStreaming: true,
                };
                appendStreamItem(sessionId, item);
                lastItemType = "thinking";
              }
              break;
            }

            // Tool call started
            case "tool_call_start": {
              finalizeStreaming();
              accumulatedText = "";
              accumulatedThinking = "";

              // Skip tool_call_start for TodoWrite — pill created on first progress
              if (parsed.isTodo) {
                lastItemType = "tool";
                break;
              }

              appendStreamItem(sessionId, {
                type: "tool_call",
                id: parsed.toolCallId,
                toolCall: {
                  id: parsed.toolCallId,
                  kind: parsed.kind,
                  title: "",
                  status: "pending",
                  description: "",
                  command: "",
                  rawOutput: "",
                  subagentType: undefined,
                  isNewFile: true,
                  oldContent: "",
                  newContent: "",
                },
              });
              lastItemType = "tool";
              break;
            }

            // Tool call progress
            case "tool_call_progress": {
              if (parsed.isTodo) {
                upsertTodoListStreamItem(sessionId, parsed.toolCallId, {
                  id: parsed.toolCallId,
                  todos: parsed.todos,
                  isOpen: true,
                });
                break;
              }

              updateToolCallStreamItem(sessionId, parsed.toolCallId, {
                status: parsed.status,
                title: parsed.title,
                description: parsed.description,
                command: parsed.command,
                rawOutput: parsed.rawOutput,
                subagentType: parsed.subagentType ?? undefined,
                ...(parsed.kind === "edit" && {
                  isNewFile: parsed.isNewFile,
                  oldContent: parsed.oldContent,
                  newContent: parsed.newContent,
                }),
              });

              // Run output file detectors (filePath is pre-sanitized)
              if (parsed.filePath && parsed.kind) {
                for (const detector of OUTPUT_FILE_DETECTORS) {
                  if (detector.match(parsed.filePath, parsed.kind)) {
                    detector.onDetect(sessionId, parsed.filePath);
                    break;
                  }
                }
              }

              // Task completion → emit text StreamItem
              if (parsed.taskOutput) {
                appendStreamItem(sessionId, {
                  type: "text",
                  id: genId("task-output"),
                  content: parsed.taskOutput,
                  isStreaming: false,
                });
                lastItemType = "text";
                accumulatedText = "";
              }
              break;
            }

            // Artifacts
            case "artifact_created": {
              const newArtifact: Artifact = {
                id: parsed.artifact.id,
                session_id: sessionId,
                type: parsed.artifact.type as ArtifactType,
                name: parsed.artifact.name,
                path: parsed.artifact.path,
                preview_url: parsed.artifact.preview_url || null,
                created_at: new Date(),
                updated_at: new Date(),
              };
              addArtifactToSession(sessionId, newArtifact);

              // If webapp, fetch session to get sandbox port
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
                  .catch((err) =>
                    console.error(
                      "Failed to fetch session for webapp URL:",
                      err
                    )
                  );
              }
              break;
            }

            // Agent finished
            case "prompt_response": {
              finalizeStreaming();

              const session = useBuildSessionStore
                .getState()
                .sessions.get(sessionId);

              if (session && session.streamItems.length > 0) {
                const textContent = session.streamItems
                  .filter((item) => item.type === "text")
                  .map((item) => item.content)
                  .join("");

                const isFirstAssistantMessage =
                  session.messages.filter((m) => m.type === "assistant")
                    .length === 0;

                const firstUserMessage = session.messages.find(
                  (m) => m.type === "user"
                );

                if (
                  isFirstAssistantMessage &&
                  firstUserMessage &&
                  textContent
                ) {
                  (async () => {
                    try {
                      setSuggestionsLoading(sessionId, true);
                      const suggestions = await generateFollowupSuggestions(
                        sessionId,
                        firstUserMessage.content,
                        textContent
                      );
                      setFollowupSuggestions(sessionId, suggestions);
                    } catch (err) {
                      console.error("Failed to generate suggestions:", err);
                      setFollowupSuggestions(sessionId, null);
                    }
                  })();
                }

                appendMessageToSession(sessionId, {
                  id: genId("assistant-msg"),
                  type: "assistant",
                  content: textContent,
                  timestamp: new Date(),
                  message_metadata: {
                    streamItems: session.streamItems.map((item) => ({
                      ...item,
                      ...(item.type === "text" || item.type === "thinking"
                        ? { isStreaming: false }
                        : {}),
                    })),
                  },
                });
              }

              updateSessionData(sessionId, {
                status: "completed",
                streamItems: [],
              });
              break;
            }

            // Error
            case "error": {
              updateSessionData(sessionId, {
                status: "failed",
                error: parsed.message,
              });
              break;
            }

            default:
              break;
          }
        });
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          // User cancelled - no error handling needed
        } else if (err instanceof RateLimitError) {
          console.warn("[Streaming] Rate limit exceeded");
          updateSessionData(sessionId, {
            status: "completed",
            error: SessionErrorCode.RATE_LIMIT_EXCEEDED,
          });
        } else {
          console.error("[Streaming] Stream error:", err);
          updateSessionData(sessionId, {
            status: "failed",
            error: (err as Error).message,
          });
        }
      } finally {
        setAbortController(sessionId, new AbortController());
      }
    },
    [
      setAbortController,
      updateSessionData,
      appendStreamItem,
      updateLastStreamingText,
      updateLastStreamingThinking,
      updateToolCallStreamItem,
      upsertTodoListStreamItem,
      clearStreamItems,
      addArtifactToSession,
      appendMessageToSession,
      OUTPUT_FILE_DETECTORS,
      setFollowupSuggestions,
      setSuggestionsLoading,
    ]
  );

  return useMemo(
    () => ({
      streamMessage,
      abortStream: abortCurrentSession,
    }),
    [streamMessage, abortCurrentSession]
  );
}
