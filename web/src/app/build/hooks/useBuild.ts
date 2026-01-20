"use client";

import { useState, useCallback, useRef } from "react";
import {
  createSession,
  deleteSession,
  executeTask,
  BuildEvent,
  ArtifactInfo,
  AgentMessageChunkEvent,
  AgentThoughtChunkEvent,
  ToolCallStartEvent,
  ToolCallProgressEvent,
  AgentPlanUpdateEvent,
} from "@/lib/build/client";

export type BuildStatus =
  | "idle"
  | "creating"
  | "running"
  | "completed"
  | "failed";

/** Types of output packets from the agent */
export type OutputPacketType =
  | "message" // Agent text output
  | "thought" // Agent reasoning
  | "tool_start" // Tool invocation started
  | "tool_progress" // Tool execution progress
  | "stdout" // Legacy stdout
  | "stderr"; // Legacy stderr

export interface OutputPacket {
  type: OutputPacketType;
  content: string;
  timestamp: number;
  /** Tool name for tool_start/tool_progress packets */
  toolName?: string;
  /** Tool call ID for correlating start/progress */
  toolCallId?: string;
}

export interface PlanItem {
  id: string;
  description: string;
  status: "pending" | "in_progress" | "completed" | "failed";
}

export interface UseBuildReturn {
  status: BuildStatus;
  sessionId: string | null;
  packets: OutputPacket[];
  artifacts: ArtifactInfo[];
  plan: PlanItem[];
  currentMode: string | null;
  error: string | null;
  run: (task: string, context?: string) => Promise<void>;
  cleanup: () => Promise<void>;
}

/**
 * Extract text content from an ACP message chunk event.
 * Handles both array content (spec) and single object content (actual backend).
 */
function extractTextFromMessageChunk(event: AgentMessageChunkEvent): string {
  const content = event.content;

  // Handle single object (actual backend format)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rawContent = content as any;
  if (rawContent && !Array.isArray(rawContent)) {
    // Single object with text property
    if (rawContent.text) {
      return rawContent.text;
    }
    return "";
  }

  // Handle array format (ACP spec)
  if (Array.isArray(content)) {
    return content
      .filter((c) => c.type === "text" && c.text)
      .map((c) => c.text!)
      .join("");
  }

  return "";
}

/**
 * Extract text content from a tool call progress event.
 * Handles the actual backend format with nested content structures.
 */
function extractTextFromToolProgress(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  event: ToolCallProgressEvent | any
): string {
  if (event.error) {
    return `Error: ${event.error}`;
  }
  if (!event.content) {
    return "";
  }

  // Backend sends content as array of objects with type and content/new_text
  if (Array.isArray(event.content)) {
    return event.content
      .map(
        (item: {
          type?: string;
          content?: { text?: string };
          text?: string;
        }) => {
          // Handle nested content object
          if (item.content && item.content.text) {
            return item.content.text;
          }
          // Handle direct text property
          if (item.text) {
            return item.text;
          }
          // Handle type="text" with text property (ACP spec)
          if (item.type === "text" && item.text) {
            return item.text;
          }
          return "";
        }
      )
      .filter(Boolean)
      .join("");
  }

  return "";
}

export function useBuild(): UseBuildReturn {
  const [status, setStatus] = useState<BuildStatus>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [packets, setPackets] = useState<OutputPacket[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [plan, setPlan] = useState<PlanItem[]>([]);
  const [currentMode, setCurrentMode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const run = useCallback(async (task: string, context?: string) => {
    setStatus("creating");
    setPackets([]);
    setArtifacts([]);
    setPlan([]);
    setCurrentMode(null);
    setError(null);

    try {
      const { session_id } = await createSession({ task });
      setSessionId(session_id);
      setStatus("running");

      await executeTask(
        session_id,
        task,
        context,
        (event: BuildEvent) => {
          const timestamp = Date.now();

          switch (event.type) {
            // New ACP event types
            case "agent_message_chunk": {
              const text = extractTextFromMessageChunk(
                event.data as AgentMessageChunkEvent
              );
              if (text) {
                setPackets((prev) => [
                  ...prev,
                  { type: "message", content: text, timestamp },
                ]);
              }
              break;
            }

            case "agent_thought_chunk": {
              const data = event.data as AgentThoughtChunkEvent;
              if (data.thought) {
                setPackets((prev) => [
                  ...prev,
                  { type: "thought", content: data.thought, timestamp },
                ]);
              }
              break;
            }

            case "tool_call": {
              // Backend uses snake_case: tool_call_id, title/kind, raw_input
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const rawData = event.data as any;
              const toolCallId = rawData.toolCallId || rawData.tool_call_id;
              const toolName =
                rawData.toolName || rawData.title || rawData.kind;
              const toolInput = rawData.toolInput || rawData.raw_input;
              const inputStr = toolInput ? JSON.stringify(toolInput) : "";
              setPackets((prev) => [
                ...prev,
                {
                  type: "tool_start",
                  content: inputStr,
                  timestamp,
                  toolName: toolName,
                  toolCallId: toolCallId,
                },
              ]);
              break;
            }

            case "tool_call_update": {
              // Backend uses snake_case: tool_call_id, and status instead of isComplete
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const rawData = event.data as any;
              const text = extractTextFromToolProgress(rawData);
              const isComplete =
                rawData.isComplete || rawData.status === "completed";
              const toolCallId = rawData.toolCallId || rawData.tool_call_id;
              const toolInput = rawData.toolInput || rawData.raw_input;

              setPackets((prev) => {
                const newPackets = [...prev];

                // If we have updated raw_input, update the corresponding tool_start packet
                if (
                  toolInput &&
                  typeof toolInput === "object" &&
                  Object.keys(toolInput).length > 0
                ) {
                  const toolStartIndex = newPackets.findIndex(
                    (p) =>
                      p.type === "tool_start" && p.toolCallId === toolCallId
                  );
                  if (toolStartIndex !== -1) {
                    const existingPacket = newPackets[toolStartIndex]!;
                    newPackets[toolStartIndex] = {
                      type: existingPacket.type,
                      timestamp: existingPacket.timestamp,
                      content: JSON.stringify(toolInput),
                      toolName: existingPacket.toolName,
                      toolCallId: existingPacket.toolCallId,
                    };
                  }
                }

                // Add progress packet if there's content or completion
                if (text || isComplete) {
                  newPackets.push({
                    type: "tool_progress",
                    content: text || (isComplete ? "[completed]" : ""),
                    timestamp,
                    toolCallId: toolCallId,
                  });
                }

                return newPackets;
              });
              break;
            }

            case "plan": {
              const data = event.data as AgentPlanUpdateEvent;
              setPlan(data.plan);
              break;
            }

            case "current_mode_update": {
              setCurrentMode(event.data.mode);
              break;
            }

            case "prompt_response": {
              // Agent finished - status event should follow
              break;
            }

            // Status and artifact events (unchanged)
            case "status":
              if (event.data.status === "completed") {
                setStatus("completed");
              } else if (event.data.status === "failed") {
                setStatus("failed");
                setError(event.data.message || "Task failed");
              }
              break;
            case "artifact":
              setArtifacts((prev) => [
                ...prev,
                {
                  artifact_type: event.data
                    .artifact_type as ArtifactInfo["artifact_type"],
                  path: event.data.path,
                  filename: event.data.filename,
                },
              ]);
              break;
            case "error":
              setStatus("failed");
              setError(event.data.message);
              break;
          }
        },
        (err) => {
          setStatus("failed");
          setError(err.message);
        },
        () => {
          // Stream complete - status should already be set by status event
        }
      );
    } catch (err) {
      setStatus("failed");
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }, []);

  const cleanup = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    if (sessionId) {
      try {
        await deleteSession(sessionId);
      } catch {
        // Ignore cleanup errors
      }
      setSessionId(null);
    }
    setStatus("idle");
    setPackets([]);
    setArtifacts([]);
    setPlan([]);
    setCurrentMode(null);
    setError(null);
  }, [sessionId]);

  return {
    status,
    sessionId,
    packets,
    artifacts,
    plan,
    currentMode,
    error,
    run,
    cleanup,
  };
}
