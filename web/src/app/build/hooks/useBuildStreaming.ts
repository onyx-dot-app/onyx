"use client";

import { useCallback, useMemo } from "react";

import {
  Artifact,
  ArtifactType,
  ArtifactCreatedPacket,
  ErrorPacket,
} from "@/app/build/services/buildStreamingModels";

import {
  sendMessageStream,
  processSSEStream,
  fetchSession,
} from "@/app/build/services/apiServices";

import { useBuildSessionStore } from "@/app/build/hooks/useBuildSessionStore";
import {
  StreamItem,
  ToolCallState,
  ToolCallKind,
  ToolCallStatus,
} from "@/app/build/types/displayTypes";

/**
 * Generate a unique ID for stream items
 */
function genId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Extract text from ACP content structure
 */
function extractText(content: unknown): string {
  if (!content) return "";
  if (typeof content === "string") return content;
  if (typeof content === "object" && content !== null) {
    const obj = content as Record<string, unknown>;
    if (obj.type === "text" && typeof obj.text === "string") return obj.text;
    if (Array.isArray(content)) {
      return content
        .filter((c) => c?.type === "text" && typeof c.text === "string")
        .map((c) => c.text)
        .join("");
    }
    if (typeof obj.text === "string") return obj.text;
  }
  return "";
}

/**
 * Strip sandbox path prefix to get clean relative path
 * e.g., "/Users/.../sandboxes/uuid/outputs/web/app/page.tsx" -> "web/app/page.tsx"
 */
function getRelativePath(fullPath: string): string {
  if (!fullPath) return "";
  // Match /outputs/ and take everything after
  const outputsMatch = fullPath.match(/\/outputs\/(.+)$/);
  if (outputsMatch && outputsMatch[1]) return outputsMatch[1];
  // Match /sandboxes/uuid/ and take everything after
  const sandboxMatch = fullPath.match(/\/sandboxes\/[^/]+\/(.+)$/);
  if (sandboxMatch && sandboxMatch[1]) return sandboxMatch[1];
  // Fall back to just the filename
  const lastSlash = fullPath.lastIndexOf("/");
  return lastSlash >= 0 ? fullPath.slice(lastSlash + 1) : fullPath;
}

/**
 * Get human-readable title based on tool kind and name
 */
function getToolTitle(
  kind: string | null | undefined,
  toolName: string | null | undefined
): string {
  // Normalize kind - backend sends "edit" for writes
  const normalizedKind = kind === "edit" ? "other" : kind;
  const normalizedToolName = toolName?.toLowerCase();

  // First check tool name for specific mappings
  switch (normalizedToolName) {
    case "glob":
      return "Searching files";
    case "grep":
      return "Searching content";
    case "webfetch":
      return "Fetching web content";
    case "websearch":
      return "Searching web";
    case "bash":
      return "Running command";
    case "read":
      return "Reading file";
    case "write":
      return "Writing file";
    case "edit":
      return "Writing file";
  }

  // Fall back to kind-based titles
  switch (normalizedKind) {
    case "execute":
      return "Running command";
    case "read":
      return "Reading file";
    case "other":
      return "Writing file";
    case "search":
      return "Searching";
    default:
      return "Running tool";
  }
}

/**
 * Normalize tool call kind
 */
function normalizeKind(kind: string | null | undefined): ToolCallKind {
  if (kind === "execute" || kind === "read" || kind === "other") return kind;
  return "other";
}

/**
 * Normalize tool call status
 */
function normalizeStatus(status: string | null | undefined): ToolCallStatus {
  if (
    status === "pending" ||
    status === "in_progress" ||
    status === "completed" ||
    status === "failed"
  ) {
    return status;
  }
  return "pending";
}

/**
 * Extract file path from packet (for read/write tools)
 */
function getFilePath(packet: Record<string, unknown>): string {
  const rawInput = (packet.raw_input || packet.rawInput) as Record<
    string,
    unknown
  > | null;
  if (rawInput) {
    const path = (rawInput.file_path || rawInput.filePath || rawInput.path) as
      | string
      | undefined;
    if (path) return getRelativePath(path);
  }
  // Fall back to title if it looks like a path
  const title = packet.title as string | undefined;
  if (title && title.includes("/")) return getRelativePath(title);
  return "";
}

/**
 * Extract description from tool call packet
 * For file operations, returns the relative file path
 * For execute, returns the description or "Running command"
 * For search tools (glob/grep), returns the pattern
 */
function getDescription(packet: Record<string, unknown>): string {
  const kind = packet.kind as string | null;
  const normalizedKind = kind === "edit" ? "other" : kind;
  const rawInput = (packet.raw_input || packet.rawInput) as Record<
    string,
    unknown
  > | null;
  // Backend uses "title" field for tool name
  const toolName = (
    (packet.tool_name || packet.toolName || packet.title) as string | undefined
  )?.toLowerCase();

  // For file operations (read/write), description is the file path
  if (normalizedKind === "read" || normalizedKind === "other") {
    const filePath = getFilePath(packet);
    if (filePath) return filePath;
  }

  // For execute, use rawInput.description
  if (normalizedKind === "execute") {
    if (rawInput?.description && typeof rawInput.description === "string") {
      return rawInput.description;
    }
    return "Running command";
  }

  // For glob/grep (search tools), use the pattern
  if (
    (toolName === "glob" ||
      toolName === "grep" ||
      normalizedKind === "search") &&
    rawInput?.pattern &&
    typeof rawInput.pattern === "string"
  ) {
    return rawInput.pattern;
  }

  // Fallback - use tool name for display
  return getToolTitle(kind, toolName);
}

/**
 * Extract command/path from tool call packet
 * For execute: the command being run
 * For read/write: the file path
 * For glob/grep: the search pattern
 */
function getCommand(packet: Record<string, unknown>): string {
  const rawInput = (packet.raw_input || packet.rawInput) as Record<
    string,
    unknown
  > | null;
  const kind = packet.kind as string | null;
  const normalizedKind = kind === "edit" ? "other" : kind;
  // Backend uses "title" field for tool name
  const toolName = (
    (packet.tool_name || packet.toolName || packet.title) as string | undefined
  )?.toLowerCase();

  // For execute, return the command
  if (normalizedKind === "execute" && rawInput) {
    if (typeof rawInput.command === "string") return rawInput.command;
  }

  // For read/write, return the file path
  if (normalizedKind === "read" || normalizedKind === "other") {
    return getFilePath(packet);
  }

  // For glob/grep (search tools), return the pattern
  if (
    (toolName === "glob" ||
      toolName === "grep" ||
      normalizedKind === "search") &&
    rawInput?.pattern &&
    typeof rawInput.pattern === "string"
  ) {
    return rawInput.pattern;
  }

  return "";
}

/**
 * Extract file content from content array (for read operations)
 * Content comes in format: <file>...\n(End of file...)</file>
 */
function extractFileContent(content: unknown): string {
  if (!Array.isArray(content)) return "";

  for (const item of content) {
    if (item?.type === "content" && item?.content?.type === "text") {
      const text = item.content.text as string;
      // Strip <file> tags and "(End of file...)" suffix
      const fileMatch = text.match(
        /<file>\n?([\s\S]*?)\n?\(End of file[^)]*\)\n?<\/file>/
      );
      if (fileMatch && fileMatch[1]) {
        // Remove line numbers (e.g., "00001| ")
        return fileMatch[1].replace(/^\d{5}\| /gm, "");
      }
      // If no <file> tags, return as-is
      return text;
    }
  }
  return "";
}

/**
 * Extract newText from content array (for write operations)
 * The diff content has a newText field with the file contents
 */
function extractNewText(content: unknown): string {
  if (!Array.isArray(content)) return "";

  for (const item of content) {
    if (item?.type === "diff" && typeof item?.newText === "string") {
      return item.newText;
    }
  }
  return "";
}

/**
 * Extract raw output from tool call packet
 * For execute: command output
 * For read: file contents
 * For write: the content that was written
 * For glob/grep: search results
 */
function getRawOutput(packet: Record<string, unknown>): string {
  const kind = packet.kind as string | null;
  const normalizedKind = kind === "edit" ? "other" : kind;
  // Backend uses "title" field for tool name
  const toolName = (
    (packet.tool_name || packet.toolName || packet.title) as string | undefined
  )?.toLowerCase();

  // For execute, get command output
  if (normalizedKind === "execute") {
    const rawOutput = (packet.raw_output || packet.rawOutput) as Record<
      string,
      unknown
    > | null;
    if (!rawOutput) return "";
    const metadata = rawOutput.metadata as Record<string, unknown> | null;
    return (metadata?.output || rawOutput.output || "") as string;
  }

  // For read, get file content from content array
  if (normalizedKind === "read") {
    const content = packet.content;
    const fileContent = extractFileContent(content);
    if (fileContent) return fileContent;
    // Fall back to rawOutput
    const rawOutput = (packet.raw_output || packet.rawOutput) as Record<
      string,
      unknown
    > | null;
    return (rawOutput?.output || "") as string;
  }

  // For write/edit, get the content that was written
  if (normalizedKind === "other") {
    // First try content array for newText (diff)
    const content = packet.content;
    const newText = extractNewText(content);
    if (newText) return newText;

    // Fall back to rawInput.content (the content being written)
    const rawInput = (packet.raw_input || packet.rawInput) as Record<
      string,
      unknown
    > | null;
    if (rawInput?.content && typeof rawInput.content === "string") {
      return rawInput.content;
    }
    return "";
  }

  // For glob/grep (search tools), extract results from content or rawOutput
  if (
    toolName === "glob" ||
    toolName === "grep" ||
    normalizedKind === "search"
  ) {
    // Helper to clean up file paths in search results
    const cleanSearchResults = (text: string): string => {
      return text
        .split("\n")
        .map((line) =>
          line.includes("/") ? getRelativePath(line.trim()) : line
        )
        .join("\n");
    };

    // Try content array first
    const content = packet.content;
    const textContent = extractText(content);
    if (textContent) return cleanSearchResults(textContent);

    // Fall back to rawOutput
    const rawOutput = (packet.raw_output || packet.rawOutput) as Record<
      string,
      unknown
    > | null;
    if (rawOutput?.output && typeof rawOutput.output === "string") {
      return cleanSearchResults(rawOutput.output);
    }
    // Try result field
    if (rawOutput?.result && typeof rawOutput.result === "string") {
      return cleanSearchResults(rawOutput.result);
    }
    // If result is an array of files, clean up each path
    if (rawOutput?.result && Array.isArray(rawOutput.result)) {
      return (rawOutput.result as string[]).map(getRelativePath).join("\n");
    }
  }

  return "";
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
  const clearStreamItems = useBuildSessionStore(
    (state) => state.clearStreamItems
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

            // Tool call started - create new tool_call item
            case "tool_call_start": {
              // Finalize any streaming text/thinking
              finalizeStreaming();
              accumulatedText = "";
              accumulatedThinking = "";

              // DEBUG: Log full packet
              console.log(
                "[tool_call_start] Full packet:",
                JSON.stringify(packetData, null, 2)
              );

              const toolCallId = (packetData.tool_call_id ||
                packetData.toolCallId ||
                genId("tc")) as string;
              const kind = packetData.kind as string | null;
              // Backend uses "title" field for tool name (e.g., "glob", "read", "bash")
              const toolName = (packetData.tool_name ||
                packetData.toolName ||
                packetData.title) as string | null;

              console.log("[tool_call_start] Extracted:", {
                toolCallId,
                kind,
                toolName,
              });

              const toolCall: ToolCallState = {
                id: toolCallId,
                kind: normalizeKind(kind),
                title: getToolTitle(kind, toolName),
                status: "pending",
                description: getFilePath(packetData) || "",
                command: "",
                rawOutput: "",
              };

              console.log("[tool_call_start] Created toolCall:", toolCall);

              const item: StreamItem = {
                type: "tool_call",
                id: toolCallId,
                toolCall,
              };
              appendStreamItem(sessionId, item);
              lastItemType = "tool";
              break;
            }

            // Tool call progress - update existing tool_call item
            case "tool_call_progress": {
              // DEBUG: Log full packet
              console.log(
                "[tool_call_progress] Full packet:",
                JSON.stringify(packetData, null, 2)
              );

              const toolCallId = (packetData.tool_call_id ||
                packetData.toolCallId) as string;
              if (!toolCallId) break;

              const updates: Partial<ToolCallState> = {
                status: normalizeStatus(packetData.status as string | null),
                description: getDescription(packetData),
                command: getCommand(packetData),
                rawOutput: getRawOutput(packetData),
              };

              console.log("[tool_call_progress] Updates:", updates);

              updateToolCallStreamItem(sessionId, toolCallId, updates);
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
            case "prompt_response":
              finalizeStreaming();
              updateSessionData(sessionId, { status: "completed" });
              break;

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
      clearStreamItems,
      addArtifactToSession,
      appendMessageToSession,
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
