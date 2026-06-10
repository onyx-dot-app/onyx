"use client";

import { useCallback, useMemo } from "react";
import { useSWRConfig } from "swr";

import {
  Artifact,
  ArtifactType,
  SessionErrorCode,
} from "@/app/craft/types/streamingTypes";

import {
  createTurn,
  fetchActiveTurn,
  fetchTurnEventStream,
  interruptMessageStream,
  processSSEStream,
  fetchSession,
  fetchScheduledRunEventStream,
  RateLimitError,
} from "@/app/craft/services/apiServices";
import { SWR_KEYS } from "@/lib/swr-keys";

import {
  useBuildSessionStore,
  type BuildSessionData,
} from "@/app/craft/hooks/useBuildSessionStore";
import { StreamItem, ToolCallState } from "@/app/craft/types/displayTypes";

import { genId } from "@/app/craft/utils/streamItemHelpers";
import { parsePacket } from "@/app/craft/utils/parsePacket";
import {
  classifySubagentEvent,
  toolCallStateFromProgress,
  toolCallStateFromStart,
  subagentNameFromTask,
  subagentNameFromToolCall,
  cleanTaskOutput,
} from "@/app/craft/utils/subagentRouting";

const INTERRUPT_RECONCILE_INTERVAL_MS = 1000;
const INTERRUPT_RECONCILE_MAX_ATTEMPTS = 30;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function promptFromToolCall(toolCall: ToolCallState): string {
  const prompt = toolCall.command || toolCall.description || "";
  return prompt.replace(/^Spawning subagent:\s*/, "").trim();
}

function findParentTaskToolCall(
  session: BuildSessionData,
  subagentSessionId: string
): ToolCallState | null {
  const streamItems = [
    ...session.messages.flatMap((message) => {
      const items = message.message_metadata?.streamItems;
      return Array.isArray(items) ? (items as StreamItem[]) : [];
    }),
    ...session.streamItems,
  ];
  const currentParent =
    session.subagents.get(subagentSessionId)?.parentToolCallId ?? "";
  if (currentParent) {
    const parentItem = streamItems.find(
      (item) => item.type === "tool_call" && item.toolCall.id === currentParent
    );
    return parentItem?.type === "tool_call" ? parentItem.toolCall : null;
  }

  const linkedParentIds = new Set(
    Array.from(session.subagents.values())
      .map((subagent) => subagent.parentToolCallId)
      .filter(Boolean)
  );
  for (const item of [...streamItems].reverse()) {
    if (item.type !== "tool_call") continue;
    if (item.toolCall.kind !== "task" && item.toolCall.toolName !== "task") {
      continue;
    }
    if (linkedParentIds.has(item.toolCall.id)) continue;
    return item.toolCall;
  }

  return null;
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
  const cancelLatestInFlightToolCallStreamItem = useBuildSessionStore(
    (state) => state.cancelLatestInFlightToolCallStreamItem
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

  const reconcileInterruptedTurn = useCallback(
    async (
      sessionId: string,
      interruptedTurnId: string | null
    ): Promise<void> => {
      let reconciledTurnId = interruptedTurnId;
      for (
        let attempt = 0;
        attempt < INTERRUPT_RECONCILE_MAX_ATTEMPTS;
        attempt++
      ) {
        await sleep(INTERRUPT_RECONCILE_INTERVAL_MS);

        const currentSession = useBuildSessionStore
          .getState()
          .sessions.get(sessionId);
        if (
          !currentSession ||
          currentSession.status !== "running" ||
          (reconciledTurnId &&
            currentSession.activeTurnId &&
            currentSession.activeTurnId !== reconciledTurnId)
        ) {
          return;
        }

        let activeTurn: Awaited<ReturnType<typeof fetchActiveTurn>> = null;
        try {
          activeTurn = await fetchActiveTurn(sessionId);
        } catch (err) {
          console.warn(
            "[Streaming] Failed to reconcile interrupted turn:",
            err
          );
          continue;
        }

        if (activeTurn) {
          if (reconciledTurnId === null) {
            reconciledTurnId = activeTurn.turn_id;
            continue;
          }
          if (activeTurn.turn_id === reconciledTurnId) {
            continue;
          }
          return;
        }

        updateSessionData(sessionId, {
          status: "active",
          isInterrupting: false,
          activeTurnId: null,
          activeTurnIndex: null,
          activeTurnLocalOwner: false,
        });
        await useBuildSessionStore
          .getState()
          .loadSession(sessionId, { force: true })
          .catch((err) =>
            console.warn(
              "[Streaming] Failed to reload reconciled interrupted turn:",
              err
            )
          );
        return;
      }

      const currentSession = useBuildSessionStore
        .getState()
        .sessions.get(sessionId);
      if (
        currentSession?.status !== "running" ||
        (reconciledTurnId &&
          currentSession.activeTurnId &&
          currentSession.activeTurnId !== reconciledTurnId)
      ) {
        return;
      }

      console.warn("[Streaming] Interrupted turn reconciliation timed out");
      updateSessionData(sessionId, { isInterrupting: false });
    },
    [updateSessionData]
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
  const appendSubagentResponseChunk = useBuildSessionStore(
    (state) => state.appendSubagentResponseChunk
  );
  const appendSubagentThinkingChunk = useBuildSessionStore(
    (state) => state.appendSubagentThinkingChunk
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
    (
      sessionId: string,
      options?: { onPromptResponse?: () => void; expectedTurnId?: string }
    ) => {
      let accumulatedText = "";
      let accumulatedThinking = "";
      let lastItemType: "text" | "thinking" | "tool" | null = null;
      const currentItems =
        useBuildSessionStore.getState().sessions.get(sessionId)?.streamItems ??
        [];
      const lastCurrentItem = currentItems[currentItems.length - 1];
      if (lastCurrentItem?.type === "text") {
        accumulatedText = lastCurrentItem.content;
        lastItemType = "text";
        if (!lastCurrentItem.isStreaming) {
          useBuildSessionStore
            .getState()
            .updateStreamItem(sessionId, lastCurrentItem.id, {
              isStreaming: true,
            });
        }
      } else if (lastCurrentItem?.type === "thinking") {
        accumulatedThinking = lastCurrentItem.content;
        lastItemType = "thinking";
        if (!lastCurrentItem.isStreaming) {
          useBuildSessionStore
            .getState()
            .updateStreamItem(sessionId, lastCurrentItem.id, {
              isStreaming: true,
            });
        }
      }

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

      const appendErrorItem = (message: string) => {
        const content = message || "Turn failed.";
        const session = useBuildSessionStore.getState().sessions.get(sessionId);
        const lastItem = session?.streamItems[session.streamItems.length - 1];

        finalizeStreaming();
        if (lastItem?.type === "error" && lastItem.content === content) {
          return;
        }

        appendStreamItem(sessionId, {
          type: "error",
          id: genId("error"),
          content,
        });
      };

      const seedFromParentTask = (subagentSessionId: string): string => {
        const session = useBuildSessionStore.getState().sessions.get(sessionId);
        const parentToolCall = session
          ? findParentTaskToolCall(session, subagentSessionId)
          : null;
        const existing = session?.subagents.get(subagentSessionId);
        const parentToolCallId =
          parentToolCall?.id ?? existing?.parentToolCallId ?? "";

        if (parentToolCallId || parentToolCall) {
          seedSubagentMeta(
            sessionId,
            subagentSessionId,
            parentToolCallId,
            parentToolCall?.subagentType ?? null,
            parentToolCall ? subagentNameFromToolCall(parentToolCall) : "",
            parentToolCall ? promptFromToolCall(parentToolCall) : ""
          );
        }

        return parentToolCallId;
      };

      return (rawPacket: unknown) => {
        const parsed = parsePacket(rawPacket);
        if (options?.expectedTurnId && parsed.type !== "approval_requested") {
          const currentTurnId = useBuildSessionStore
            .getState()
            .sessions.get(sessionId)?.activeTurnId;
          if (currentTurnId !== options.expectedTurnId) {
            if (parsed.type === "prompt_response") {
              options.onPromptResponse?.();
            }
            return;
          }
        }

        switch (parsed.type) {
          case "text_chunk": {
            if (!parsed.text) break;

            if (parsed.parentSessionId !== null && parsed.sessionId !== null) {
              finalizeStreaming();
              accumulatedText = "";
              accumulatedThinking = "";
              lastItemType = null;
              seedFromParentTask(parsed.sessionId);
              appendSubagentResponseChunk(
                sessionId,
                parsed.sessionId,
                parsed.text
              );
              break;
            }

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

            if (parsed.parentSessionId !== null && parsed.sessionId !== null) {
              finalizeStreaming();
              accumulatedText = "";
              accumulatedThinking = "";
              lastItemType = null;
              seedFromParentTask(parsed.sessionId);
              appendSubagentThinkingChunk(
                sessionId,
                parsed.sessionId,
                parsed.text
              );
              break;
            }

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

          case "subagent_started": {
            if (!parsed.subagentSessionId) break;
            seedFromParentTask(parsed.subagentSessionId);
            break;
          }

          case "tool_call_start": {
            finalizeStreaming();
            accumulatedText = "";
            accumulatedThinking = "";

            // Child (subagent-internal) start: do not add to main transcript.
            // Record it in the subagent stream immediately so in-progress
            // tools show before their first progress packet arrives.
            if (parsed.parentSessionId !== null && parsed.sessionId !== null) {
              const parentToolCallId = seedFromParentTask(parsed.sessionId);
              recordSubagentToolCall(
                sessionId,
                parsed.sessionId,
                parentToolCallId,
                toolCallStateFromStart(parsed),
                parsed.subagentType,
                ""
              );
              lastItemType = "tool";
              break;
            }

            const isInterrupting = useBuildSessionStore
              .getState()
              .sessions.get(sessionId)?.isInterrupting;
            const startedToolCall = {
              ...toolCallStateFromStart(parsed),
              status: isInterrupting ? "cancelled" : "pending",
            } satisfies ToolCallState;

            // Parent `task` start packets can carry the spawned child session
            // before any progress packet arrives. Seed immediately so the task
            // row has a click target while the subagent is still running.
            if (parsed.subagentSessionId !== null) {
              seedSubagentMeta(
                sessionId,
                parsed.subagentSessionId,
                parsed.toolCallId,
                parsed.subagentType,
                subagentNameFromToolCall(startedToolCall),
                promptFromToolCall(startedToolCall)
              );
            }

            // Skip tool_call_start for TodoWrite; pill is created on progress.
            if (parsed.isTodo) {
              lastItemType = "tool";
              break;
            }

            appendStreamItem(sessionId, {
              type: "tool_call",
              id: parsed.toolCallId,
              toolCall: startedToolCall,
            });
            lastItemType = "tool";
            break;
          }

          case "tool_call_progress": {
            const subagentClass = classifySubagentEvent(parsed);

            // Child (subagent-internal) event: route to the subagent's own
            // tool-call list, not the main transcript.
            if (subagentClass.kind === "child") {
              const parentToolCallId = seedFromParentTask(
                subagentClass.subagentSessionId
              );
              recordSubagentToolCall(
                sessionId,
                subagentClass.subagentSessionId,
                parentToolCallId,
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

            if (
              subagentClass.kind === "normal" &&
              (parsed.kind === "task" || parsed.toolName === "task")
            ) {
              const session = useBuildSessionStore
                .getState()
                .sessions.get(sessionId);
              const subagent = Array.from(
                session?.subagents.values() ?? []
              ).find((candidate) => {
                return candidate.parentToolCallId === parsed.toolCallId;
              });
              if (subagent) {
                seedSubagentMeta(
                  sessionId,
                  subagent.sessionId,
                  parsed.toolCallId,
                  parsed.subagentType,
                  subagentNameFromTask(parsed),
                  parsed.command
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

            const status =
              useBuildSessionStore.getState().sessions.get(sessionId)
                ?.isInterrupting &&
              (parsed.status === "pending" || parsed.status === "in_progress")
                ? "cancelled"
                : parsed.status;

            updateToolCallStreamItem(sessionId, parsed.toolCallId, {
              status,
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
            if (
              useBuildSessionStore.getState().sessions.get(sessionId)
                ?.isInterrupting
            ) {
              cancelLatestInFlightToolCallStreamItem(sessionId);
            }

            const session = useBuildSessionStore
              .getState()
              .sessions.get(sessionId);

            if (session && session.streamItems.length > 0) {
              const savedStreamItems = session.streamItems.map((item) => ({
                ...item,
                ...(item.type === "text" || item.type === "thinking"
                  ? { isStreaming: false }
                  : {}),
              }));
              const textContent = session.streamItems
                .filter((item) => item.type === "text")
                .map((item) => item.content)
                .join("");

              appendMessageToSession(sessionId, {
                id: genId("agent-msg"),
                type: "assistant",
                content: textContent,
                timestamp: new Date(),
                turn_index: session.activeTurnIndex ?? undefined,
                message_metadata: {
                  streamItems: savedStreamItems,
                },
              });
            }

            updateSessionData(sessionId, {
              status: "active",
              streamItems: [],
              isInterrupting: false,
              activeTurnId: null,
              activeTurnIndex: null,
              activeTurnLocalOwner: false,
            });
            options?.onPromptResponse?.();
            break;
          }

          case "approval_requested": {
            void globalMutate(SWR_KEYS.buildSessionLiveApprovals(sessionId));
            break;
          }

          case "error": {
            appendErrorItem(parsed.message);
            updateSessionData(sessionId, {
              status: "failed",
              error: parsed.message,
              isInterrupting: false,
              activeTurnId: null,
              activeTurnIndex: null,
              activeTurnLocalOwner: false,
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
      cancelLatestInFlightToolCallStreamItem,
      upsertTodoListStreamItem,
      addArtifactToSession,
      appendMessageToSession,
      OUTPUT_FILE_DETECTORS,
      globalMutate,
      recordSubagentToolCall,
      seedSubagentMeta,
      markSubagentComplete,
      appendSubagentResponseChunk,
      appendSubagentThinkingChunk,
    ]
  );

  /**
   * Attach to a background turn's live event stream.
   */
  const streamTurnEvents = useCallback(
    async (
      sessionId: string,
      turnId: string,
      signal: AbortSignal,
      onSettled?: () => void
    ): Promise<void> => {
      const existingSession = useBuildSessionStore
        .getState()
        .sessions.get(sessionId);
      if (
        existingSession?.activeTurnId === turnId &&
        existingSession.activeTurnLocalOwner &&
        existingSession.abortController.signal !== signal
      ) {
        return;
      }

      updateSessionData(sessionId, {
        status: "running",
        isInterrupting:
          existingSession?.activeTurnId === turnId
            ? existingSession.isInterrupting
            : false,
        activeTurnId: turnId,
      });
      if (existingSession?.activeTurnId !== turnId) {
        clearStreamItems(sessionId);
      }

      let settledFromPromptResponse = false;
      let transportError = false;
      const processor = createStreamPacketProcessor(sessionId, {
        expectedTurnId: turnId,
        onPromptResponse: () => {
          settledFromPromptResponse = true;
          onSettled?.();
        },
      });
      const clearTurnIfCurrent = (
        updates: Partial<{
          status: "active" | "failed";
          error: string;
          isInterrupting: boolean;
        }>
      ) => {
        const currentSession = useBuildSessionStore
          .getState()
          .sessions.get(sessionId);
        if (currentSession?.activeTurnId !== turnId) {
          return;
        }
        updateSessionData(sessionId, {
          ...updates,
          activeTurnId: null,
          activeTurnIndex: null,
          activeTurnLocalOwner: false,
        });
      };

      try {
        const response = await fetchTurnEventStream(sessionId, turnId, signal);
        if (!response) {
          clearTurnIfCurrent({
            status: "active",
            isInterrupting: false,
          });
          return;
        }
        await processSSEStream(response, processor);
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          const currentSession = useBuildSessionStore
            .getState()
            .sessions.get(sessionId);
          if (currentSession?.activeTurnId === turnId) {
            updateSessionData(sessionId, { isInterrupting: false });
          }
          return;
        }

        transportError = true;
        console.warn("[Streaming] Turn attach stream error:", err);
        const currentSession = useBuildSessionStore
          .getState()
          .sessions.get(sessionId);
        if (currentSession?.activeTurnId === turnId) {
          updateSessionData(sessionId, {
            status: "running",
            isInterrupting: false,
          });
        }
      } finally {
        if (!signal.aborted) {
          const currentSession = useBuildSessionStore
            .getState()
            .sessions.get(sessionId);
          if (
            !transportError &&
            currentSession?.status === "running" &&
            currentSession?.activeTurnId === turnId
          ) {
            clearTurnIfCurrent({
              status: "active",
              isInterrupting: false,
            });
          }
          const settledStatus = useBuildSessionStore
            .getState()
            .sessions.get(sessionId)?.status;
          if (settledStatus !== "failed") {
            await useBuildSessionStore
              .getState()
              .loadSession(sessionId, { force: true })
              .catch((err) =>
                console.warn("[Streaming] Failed to reload settled turn:", err)
              );
          }
          if (!settledFromPromptResponse) {
            onSettled?.();
          }
        }
      }
    },
    [updateSessionData, clearStreamItems, createStreamPacketProcessor]
  );

  /**
   * Start an interactive backend turn, then attach to its event stream.
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
        activeTurnId: null,
        activeTurnIndex: null,
        activeTurnLocalOwner: true,
      });
      clearStreamItems(sessionId);

      try {
        const turn = await createTurn(
          sessionId,
          content,
          crypto.randomUUID(),
          controller.signal,
          model
        );
        updateSessionData(sessionId, {
          activeTurnId: turn.turn_id,
          activeTurnIndex: turn.turn_index,
          activeTurnLocalOwner: true,
        });

        await streamTurnEvents(sessionId, turn.turn_id, controller.signal);
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          updateSessionData(sessionId, { isInterrupting: false });
        } else if (err instanceof RateLimitError) {
          console.warn("[Streaming] Rate limit exceeded");
          updateSessionData(sessionId, {
            status: "active",
            error: SessionErrorCode.RATE_LIMIT_EXCEEDED,
            isInterrupting: false,
            activeTurnId: null,
            activeTurnIndex: null,
            activeTurnLocalOwner: false,
          });
        } else {
          console.error("[Streaming] Stream error:", err);
          updateSessionData(sessionId, {
            status: "failed",
            error: (err as Error).message,
            isInterrupting: false,
            activeTurnId: null,
            activeTurnIndex: null,
            activeTurnLocalOwner: false,
          });
        }
      } finally {
        setAbortController(sessionId, new AbortController());
      }
    },
    [setAbortController, updateSessionData, clearStreamItems, streamTurnEvents]
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

      const interruptedTurnId = session.activeTurnId;
      updateSessionData(sessionId, { isInterrupting: true });
      cancelLatestInFlightToolCallStreamItem(sessionId);
      try {
        await interruptMessageStream(sessionId);
        void reconcileInterruptedTurn(sessionId, interruptedTurnId);
      } catch (err) {
        console.error("[Streaming] Failed to interrupt:", err);
        updateSessionData(sessionId, { isInterrupting: false });
      }
    },
    [
      reconcileInterruptedTurn,
      updateSessionData,
      cancelLatestInFlightToolCallStreamItem,
    ]
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
      streamTurnEvents,
      abortStream: abortCurrentSession,
    }),
    [
      streamMessage,
      interruptStreaming,
      streamScheduledRunEvents,
      streamTurnEvents,
      abortCurrentSession,
    ]
  );
}
