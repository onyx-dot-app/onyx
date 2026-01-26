"use client";

import { useCallback, useMemo } from "react";

import {
  Artifact,
  ArtifactType,
  ArtifactCreatedPacket,
  ErrorPacket,
} from "@/app/build/types/streamingTypes";

import {
  sendMessageStream,
  processSSEStream,
  fetchSession,
  generateFollowupSuggestions,
} from "@/app/build/services/apiServices";

import { useBuildSessionStore } from "@/app/build/hooks/useBuildSessionStore";
import { StreamItem, ToolCallState } from "@/app/build/types/displayTypes";

import {
  genId,
  extractText,
  getToolTitle,
  normalizeKind,
  normalizeStatus,
  getDescription,
  getCommand,
  getSubagentType,
  getRawOutput,
  getTaskOutput,
  isTaskTool,
  isTodoWriteTool,
  extractTodos,
  isNewFileOperation,
  extractDiffData,
} from "@/app/build/utils/streamItemHelpers";

/**
 * Extract file path from a tool call packet.
 */
function getFilePath(packet: Record<string, unknown>): string | null {
  // Handle both snake_case (raw_input) and camelCase (rawInput) variants
  const rawInput = (packet.raw_input ?? packet.rawInput) as Record<
    string,
    unknown
  > | null;
  return (rawInput?.file_path ?? rawInput?.filePath ?? rawInput?.path) as
    | string
    | null;
}

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
  const setFollowupSuggestions = useBuildSessionStore(
    (state) => state.setFollowupSuggestions
  );
  const setSuggestionsLoading = useBuildSessionStore(
    (state) => state.setSuggestionsLoading
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

        await processSSEStream(response, (packet) => {
          const packetData = packet as Record<string, unknown>;

          switch (packet.type) {
            // Agent message content - accumulate and update/create text item
            case "agent_message_chunk": {
              const text = extractText(packetData.content);
              if (!text) break;

              accumulatedText += text;

              if (lastItemType === "text") {
                // Update existing streaming text item
                updateLastStreamingText(sessionId, accumulatedText);
              } else {
                // Finalize previous item and create new text item
                finalizeStreaming();
                accumulatedText = text; // Reset accumulator for new item
                const item: StreamItem = {
                  type: "text",
                  id: genId("text"),
                  content: text,
                  isStreaming: true,
                };
                appendStreamItem(sessionId, item);
                lastItemType = "text";
              }
              break;
            }

            // Agent thinking - accumulate and update/create thinking item
            case "agent_thought_chunk": {
              const thought = extractText(packetData.content);
              if (!thought) break;

              accumulatedThinking += thought;

              if (lastItemType === "thinking") {
                // Update existing streaming thinking item
                updateLastStreamingThinking(sessionId, accumulatedThinking);
              } else {
                // Finalize previous item and create new thinking item
                finalizeStreaming();
                accumulatedThinking = thought; // Reset accumulator for new item
                const item: StreamItem = {
                  type: "thinking",
                  id: genId("thinking"),
                  content: thought,
                  isStreaming: true,
                };
                appendStreamItem(sessionId, item);
                lastItemType = "thinking";
              }
              break;
            }

            // Tool call started - create new tool_call item or todo_list item
            case "tool_call_start": {
              // Finalize any streaming text/thinking
              finalizeStreaming();
              accumulatedText = "";
              accumulatedThinking = "";

              const toolCallId = (packetData.tool_call_id ||
                packetData.toolCallId ||
                genId("tc")) as string;
              const kind = packetData.kind as string | null;
              // Backend uses "title" field for tool name (e.g., "glob", "read", "bash")
              const toolName = (packetData.tool_name ||
                packetData.toolName ||
                packetData.title) as string | null;

              // Check if this is a TodoWrite call
              // Skip tool_call_start for TodoWrite - it has no todos yet
              // The pill will be created on the first tool_call_progress with actual todo items
              if (isTodoWriteTool(packetData)) {
                lastItemType = "tool"; // Still track as tool for finalization
                break;
              }

              // Extract diff data for edit operations (write vs edit distinction)
              const isNewFile = isNewFileOperation(packetData);
              const diffData =
                kind === "edit"
                  ? extractDiffData(packetData.content)
                  : { oldText: "", newText: "", isNewFile: true };

              const toolCall: ToolCallState = {
                id: toolCallId,
                kind: normalizeKind(kind, packetData), // Pass packet for proper task detection
                title: getToolTitle(kind, toolName, isNewFile),
                status: "pending",
                description: getDescription(packetData),
                command: getCommand(packetData),
                rawOutput: "",
                subagentType: getSubagentType(packetData),
                // Edit operation fields
                isNewFile: isNewFile ?? true,
                oldContent: diffData.oldText,
                newContent: diffData.newText,
              };

              const item: StreamItem = {
                type: "tool_call",
                id: toolCallId,
                toolCall,
              };
              appendStreamItem(sessionId, item);
              lastItemType = "tool";
              break;
            }

            // Tool call progress - update existing tool_call item or todo_list item
            case "tool_call_progress": {
              const toolCallId = (packetData.tool_call_id ||
                packetData.toolCallId) as string;
              if (!toolCallId) break;

              // Check if this is a TodoWrite update
              // Use upsert: creates todo_list on first progress, updates on subsequent
              if (isTodoWriteTool(packetData)) {
                const todos = extractTodos(packetData);
                upsertTodoListStreamItem(sessionId, toolCallId, {
                  id: toolCallId,
                  todos,
                  isOpen: true, // Open by default during streaming
                });
                break;
              }

              const status = normalizeStatus(
                packetData.status as string | null
              );
              const kind = packetData.kind as string | null;

              // Extract diff data for edit operations (write vs edit distinction)
              const isNewFile = isNewFileOperation(packetData);
              const diffData =
                kind === "edit"
                  ? extractDiffData(packetData.content)
                  : { oldText: "", newText: "", isNewFile: true };

              const updates: Partial<ToolCallState> = {
                status,
                description: getDescription(packetData),
                command: getCommand(packetData),
                rawOutput: getRawOutput(packetData),
                subagentType: getSubagentType(packetData),
                // Edit operation fields (update when diff data becomes available)
                ...(kind === "edit" && {
                  isNewFile: isNewFile ?? true,
                  oldContent: diffData.oldText,
                  newContent: diffData.newText,
                }),
              };

              updateToolCallStreamItem(sessionId, toolCallId, updates);

              // Check if this is a file operation in web/ directory
              // Match both absolute paths (/outputs/web/...) and relative paths (web/...)
              const filePath = getFilePath(packetData);
              const isWebFile =
                (kind === "edit" || kind === "write") &&
                filePath &&
                (filePath.includes("/web/") || filePath.startsWith("web/"));

              // Trigger refresh when we see a web file being edited
              // The output panel will open when streaming ends
              if (isWebFile) {
                triggerWebappRefresh(sessionId);
              }

              // If task tool completed, extract output and create text StreamItem
              if (isTaskTool(packetData) && status === "completed") {
                const taskOutput = getTaskOutput(packetData);
                if (taskOutput) {
                  // Create a new text item for the task output
                  const textItem: StreamItem = {
                    type: "text",
                    id: genId("task-output"),
                    content: taskOutput,
                    isStreaming: false,
                  };
                  appendStreamItem(sessionId, textItem);
                  // Reset tracking so subsequent text is a new item
                  lastItemType = "text";
                  accumulatedText = "";
                }
              }
              break;
            }

            // Artifacts
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

              // Save the assistant response as a message before clearing stream items
              const session = useBuildSessionStore
                .getState()
                .sessions.get(sessionId);

              if (session && session.streamItems.length > 0) {
                // Collect text content for the message content field
                const textContent = session.streamItems
                  .filter((item) => item.type === "text")
                  .map((item) => item.content)
                  .join("");

                // Check if this is the first assistant message
                const isFirstAssistantMessage =
                  session.messages.filter((m) => m.type === "assistant")
                    .length === 0;

                // Get first user message for suggestion generation
                const firstUserMessage = session.messages.find(
                  (m) => m.type === "user"
                );

                // Generate suggestions asynchronously (don't block) after first response
                if (
                  isFirstAssistantMessage &&
                  firstUserMessage &&
                  textContent
                ) {
                  // Fire and forget - don't await
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

                // Save the complete stream items in message_metadata for full rendering
                appendMessageToSession(sessionId, {
                  id: genId("assistant-msg"),
                  type: "assistant",
                  content: textContent,
                  timestamp: new Date(),
                  message_metadata: {
                    streamItems: session.streamItems.map((item) => ({
                      ...item,
                      // Mark all items as no longer streaming
                      ...(item.type === "text" || item.type === "thinking"
                        ? { isStreaming: false }
                        : {}),
                    })),
                  },
                });
              }

              // Check if we had a web/ file change - if so, open output panel
              const shouldOpenPanel = session?.webappNeedsRefresh === true;
              updateSessionData(sessionId, {
                status: "completed",
                streamItems: [], // Clear stream items since they're now saved in the message
                ...(shouldOpenPanel && { outputPanelOpen: true }),
              });
              break;
            }

            // Error
            case "error": {
              const errPacket = packet as ErrorPacket;
              updateSessionData(sessionId, {
                status: "failed",
                error: errPacket.message || (packetData.message as string),
              });
              break;
            }

            default:
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
      triggerWebappRefresh,
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
