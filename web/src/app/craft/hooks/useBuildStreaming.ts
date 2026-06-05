"use client";

import { useCallback, useMemo } from "react";
import { useSWRConfig } from "swr";

import {
  Artifact,
  ArtifactType,
  SessionErrorCode,
} from "@/app/craft/types/streamingTypes";

import {
  sendMessageStream,
  interruptMessageStream,
  processSSEStream,
  fetchSession,
  fetchScheduledRunEventStream,
  RateLimitError,
} from "@/app/craft/services/apiServices";
import { SWR_KEYS } from "@/lib/swr-keys";

import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { StreamItem } from "@/app/craft/types/displayTypes";

import { genId } from "@/app/craft/utils/streamItemHelpers";
import { parsePacket } from "@/app/craft/utils/parsePacket";
import {
  classifySubagentEvent,
  toolCallStateFromProgress,
  subagentNameFromTask,
  cleanTaskOutput,
} from "@/app/craft/utils/subagentRouting";

/**
 * Hook for handling message streaming in build sessions.
 *
 * Uses a simple FIFO approach:
 * - Stream items are appended in chronological order as packets arrive
 * - Text/thinking chunks are merged when consecutive
 * - Tool calls are interleaved with text in the exact order they arrive
 */
export function useBuildStreaming() {
  const { mutate: globalMutate } = useSWRConfig();
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

  // Subagent routing actions
  const recordSubagentToolCall = useBuildSessionStore(
    (state) => state.recordSubagentToolCall
  );
  const seedSubagentMeta = useBuildSessionStore(
    (state) => state.seedSubagentMeta
  );
  const markSubagentComplete = useBuildSessionStore(
    (state) => state.markSubagentComplete
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

  const createStreamPacketProcessor = useCallback(
    (sessionId: string, options?: { onPromptResponse?: () => void }) => {
      let accumulatedText = "";
      let accumulatedThinking = "";
      let lastItemType: "text" | "thinking" | "tool" | null = null;

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

      return (rawPacket: unknown) => {
        const parsed = parsePacket(rawPacket);

        switch (parsed.type) {
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

          case "tool_call_start": {
            finalizeStreaming();
            accumulatedText = "";
            accumulatedThinking = "";

            // Child (subagent-internal) start: do not add to main transcript.
            // The subagent pill is created from its progress events.
            if (parsed.parentSessionId !== null && parsed.sessionId !== null) {
              lastItemType = "tool";
              break;
            }

            // Skip tool_call_start for TodoWrite; pill is created on progress.
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
                toolName: parsed.toolName,
                title: parsed.title,
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

          case "tool_call_progress": {
            const subagentClass = classifySubagentEvent(parsed);

            // Child (subagent-internal) event: route to the subagent's own
            // tool-call list, not the main transcript.
            if (subagentClass.kind === "child") {
              recordSubagentToolCall(
                sessionId,
                subagentClass.subagentSessionId,
                "",
                toolCallStateFromProgress(parsed),
                null,
                ""
              );
              if (parsed.filePath && parsed.kind) {
                for (const detector of OUTPUT_FILE_DETECTORS) {
                  if (detector.match(parsed.filePath, parsed.kind)) {
                    detector.onDetect(sessionId, parsed.filePath);
                    break;
                  }
                }
              }
              break;
            }

            // Parent `task` event: keep the transcript task card and seed/update
            // the subagent meta and completion state.
            if (subagentClass.kind === "parentTask") {
              seedSubagentMeta(
                sessionId,
                subagentClass.subagentSessionId,
                parsed.toolCallId,
                parsed.subagentType,
                subagentNameFromTask(parsed),
                parsed.command
              );
              if (parsed.status === "completed") {
                markSubagentComplete(
                  sessionId,
                  subagentClass.subagentSessionId,
                  "done",
                  cleanTaskOutput(parsed.taskOutput)
                );
              } else if (
                parsed.status === "failed" ||
                parsed.status === "cancelled"
              ) {
                markSubagentComplete(
                  sessionId,
                  subagentClass.subagentSessionId,
                  "failed",
                  cleanTaskOutput(parsed.taskOutput)
                );
              }
            }

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
              toolName: parsed.toolName,
              subagentType: parsed.subagentType ?? undefined,
              skillName: parsed.skillName ?? undefined,
              taskOutput: parsed.taskOutput ?? undefined,
              ...(parsed.kind === "edit" && {
                isNewFile: parsed.isNewFile,
                oldContent: parsed.oldContent,
                newContent: parsed.newContent,
              }),
            });

            if (parsed.filePath && parsed.kind) {
              for (const detector of OUTPUT_FILE_DETECTORS) {
                if (detector.match(parsed.filePath, parsed.kind)) {
                  detector.onDetect(sessionId, parsed.filePath);
                  break;
                }
              }
            }
            break;
          }

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
                  console.error("Failed to fetch session for webapp URL:", err)
                );
            }
            break;
          }

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

              appendMessageToSession(sessionId, {
                id: genId("agent-msg"),
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
              status: "active",
              streamItems: [],
              isInterrupting: false,
            });
            options?.onPromptResponse?.();
            break;
          }

          case "approval_requested": {
            void globalMutate(SWR_KEYS.buildSessionLiveApprovals(sessionId));
            break;
          }

          case "error": {
            updateSessionData(sessionId, {
              status: "failed",
              error: parsed.message,
              isInterrupting: false,
            });
            break;
          }

          default:
            break;
        }
      };
    },
    [
      updateSessionData,
      appendStreamItem,
      updateLastStreamingText,
      updateLastStreamingThinking,
      updateToolCallStreamItem,
      upsertTodoListStreamItem,
      addArtifactToSession,
      appendMessageToSession,
      OUTPUT_FILE_DETECTORS,
      globalMutate,
      recordSubagentToolCall,
      seedSubagentMeta,
      markSubagentComplete,
    ]
  );

  /**
   * Stream a message to the given session and process the SSE response.
   * Populates streamItems in FIFO order as packets arrive.
   */
  const streamMessage = useCallback(
    async (
      sessionId: string,
      content: string,
      model?: { provider: string; modelName: string } | null
    ): Promise<void> => {
      const currentState = useBuildSessionStore.getState();
      const existingSession = currentState.sessions.get(sessionId);

      if (existingSession?.abortController) {
        existingSession.abortController.abort();
      }

      const controller = new AbortController();
      setAbortController(sessionId, controller);

      updateSessionData(sessionId, {
        status: "running",
        isInterrupting: false,
      });
      clearStreamItems(sessionId);

      try {
        const response = await sendMessageStream(
          sessionId,
          content,
          controller.signal,
          model
        );

        await processSSEStream(
          response,
          createStreamPacketProcessor(sessionId)
        );
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          updateSessionData(sessionId, { isInterrupting: false });
        } else if (err instanceof RateLimitError) {
          console.warn("[Streaming] Rate limit exceeded");
          updateSessionData(sessionId, {
            status: "active",
            error: SessionErrorCode.RATE_LIMIT_EXCEEDED,
            isInterrupting: false,
          });
        } else {
          console.error("[Streaming] Stream error:", err);
          updateSessionData(sessionId, {
            status: "failed",
            error: (err as Error).message,
            isInterrupting: false,
          });
        }
      } finally {
        setAbortController(sessionId, new AbortController());
      }
    },
    [
      setAbortController,
      updateSessionData,
      clearStreamItems,
      createStreamPacketProcessor,
    ]
  );

  /**
   * Interrupt the in-flight turn for a session. The open SSE stream terminates
   * normally so partial output can still be committed.
   */
  const interruptStreaming = useCallback(
    async (sessionId: string): Promise<void> => {
      const session = useBuildSessionStore.getState().sessions.get(sessionId);
      if (!session || session.status !== "running" || session.isInterrupting) {
        return;
      }

      updateSessionData(sessionId, { isInterrupting: true });
      try {
        await interruptMessageStream(sessionId);
      } catch (err) {
        console.error("[Streaming] Failed to interrupt:", err);
        updateSessionData(sessionId, { isInterrupting: false });
      }
    },
    [updateSessionData]
  );

  const streamScheduledRunEvents = useCallback(
    async (
      sessionId: string,
      signal: AbortSignal,
      onSettled?: () => void
    ): Promise<void> => {
      updateSessionData(sessionId, { status: "running" });
      clearStreamItems(sessionId);
      let settledFromPromptResponse = false;

      try {
        const response = await fetchScheduledRunEventStream(sessionId, signal);
        await processSSEStream(
          response,
          createStreamPacketProcessor(sessionId, {
            onPromptResponse: () => {
              settledFromPromptResponse = true;
              onSettled?.();
            },
          })
        );
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          return;
        }

        console.error("[Streaming] Scheduled run stream error:", err);
        updateSessionData(sessionId, {
          status: "failed",
          error: (err as Error).message,
        });
      } finally {
        if (!signal.aborted) {
          // Only settle to "active" if the stream is still in-flight. An
          // in-band "error" packet (or a thrown error) already moved the status
          // to "failed", and a "prompt_response" packet already moved it to
          // "active" — overwriting either here would mask the real outcome.
          const currentStatus = useBuildSessionStore
            .getState()
            .sessions.get(sessionId)?.status;
          if (currentStatus === "running") {
            updateSessionData(sessionId, { status: "active" });
          }
          if (!settledFromPromptResponse) {
            onSettled?.();
          }
        }
      }
    },
    [updateSessionData, clearStreamItems, createStreamPacketProcessor]
  );

  return useMemo(
    () => ({
      streamMessage,
      interruptStreaming,
      streamScheduledRunEvents,
      abortStream: abortCurrentSession,
    }),
    [
      streamMessage,
      interruptStreaming,
      streamScheduledRunEvents,
      abortCurrentSession,
    ]
  );
}
