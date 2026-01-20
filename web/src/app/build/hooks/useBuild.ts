"use client";

import { useState, useCallback, useRef } from "react";
import {
  createSession,
  deleteSession,
  executeTask,
  sendMessage,
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

      // Use the new sendMessage API endpoint
      await sendMessage(
        session_id,
        task,
        (event: BuildEvent) => {
          const timestamp = Date.now();

          switch (event.type) {
            // ACP event types (direct from backend)
            case "agent_message_chunk": {
              // ACP format: content is an object with type and text
              const data = event.data as any;
              let content = "";
              // Handle ACP content structure
              if (data.content) {
                if (data.content.type === "text" && data.content.text) {
                  content = data.content.text;
                } else if (Array.isArray(data.content)) {
                  content = data.content
                    .filter((c: any) => c.type === "text" && c.text)
                    .map((c: any) => c.text)
                    .join("");
                }
              }
              if (content) {
                setPackets((prev) => [
                  ...prev,
                  { type: "message", content, timestamp },
                ]);
              }
              break;
            }

            case "agent_thought_chunk": {
              // ACP format: content is an object with type and text
              const data = event.data as any;
              let content = "";
              if (data.content) {
                if (data.content.type === "text" && data.content.text) {
                  content = data.content.text;
                }
              }
              if (content) {
                setPackets((prev) => [
                  ...prev,
                  { type: "thought", content, timestamp },
                ]);
              }
              break;
            }

            case "tool_call": {
              // ACP format: kind (tool type), title, tool_call_id
              const data = event.data as any;
              const toolName = data.kind || data.tool_name || "unknown";
              const title = data.title || "";
              setPackets((prev) => [
                ...prev,
                {
                  type: "tool_start",
                  content: title,
                  timestamp,
                  toolName: toolName,
                  toolCallId: data.tool_call_id,
                },
              ]);
              break;
            }

            case "tool_call_update": {
              // ACP format: kind, status, title, tool_call_id
              const data = event.data as any;
              const toolName = data.kind || data.tool_name || "";
              const status = data.status || "completed";
              const title = data.title || "";
              setPackets((prev) => [
                ...prev,
                {
                  type: "tool_progress",
                  content: title || `[${status}]`,
                  timestamp,
                  toolName: toolName,
                  toolCallId: data.tool_call_id,
                },
              ]);
              break;
            }

            case "plan": {
              // ACP format: plan.entries array
              const data = event.data as any;
              if (data.plan && data.plan.entries) {
                setPlan(data.plan.entries);
              } else if (data.plan) {
                setPlan(data.plan);
              }
              break;
            }

            case "current_mode_update": {
              const data = event.data as any;
              if (data.mode) {
                setCurrentMode(data.mode);
              }
              break;
            }

            case "prompt_response": {
              // Agent finished
              setStatus("completed");
              break;
            }

            case "artifact": {
              // Messages API format: artifact object with id, type, name, path
              const data = event.data as any;
              if (data.artifact) {
                const artifact = data.artifact;
                setArtifacts((prev) => [
                  ...prev,
                  {
                    artifact_type:
                      artifact.type as ArtifactInfo["artifact_type"],
                    path: artifact.path,
                    filename: artifact.name,
                  },
                ]);
              }
              break;
            }

            case "file_write": {
              // Custom Onyx packet: file was written
              const data = event.data as any;
              console.debug(
                "[Build] File written:",
                data.path,
                data.size_bytes
              );
              // Could track file writes in state if needed
              break;
            }

            case "error": {
              const data = event.data as any;
              setStatus("failed");
              setError(data.message || "An error occurred");
              break;
            }
          }
        },
        (err) => {
          setStatus("failed");
          setError(err.message);
        },
        () => {
          // Stream complete - if not already set to failed, mark as completed
          setStatus((current) =>
            current === "failed" ? "failed" : "completed"
          );
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
