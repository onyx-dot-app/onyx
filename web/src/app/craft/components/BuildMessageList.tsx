"use client";

import { useEffect, useMemo } from "react";
import useSWR from "swr";
import { cn } from "@opal/utils";
import { CopyButton } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgAlertCircle } from "@opal/icons";
import { FoldableLogo } from "@/lib/app/components";
import SetupCard from "@/app/craft/components/setup-requests/SetupCard";
import { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import TextChunk from "@/app/craft/components/TextChunk";
import CraftTimeline from "@/lib/timeline/craft/components/CraftTimeline";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
import { TimelineHeaderRow } from "@/lib/timeline/components/primitives/TimelineHeaderRow";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { ErrorBanner } from "@/app/app/message/Resubmit";
import { RATE_LIMITED_ERROR_CODE, RateLimitDetails } from "@/app/app/types";
import { convertMarkdownTablesToTsv } from "@/app/app/message/copyingUtils";
import CompactionMarker from "@/app/craft/components/CompactionMarker";
import TodoListCard from "@/app/craft/components/TodoListCard";
import HumanMessage from "@/app/app/message/HumanMessage";
import CraftMessageAttachments from "@/app/craft/components/CraftMessageAttachments";
import TurnOutputCards from "@/app/craft/components/TurnOutputCards";
import {
  BuildMessage,
  type OutputCard,
} from "@/app/craft/types/streamingTypes";
import { TodoListState } from "@/app/craft/types/displayTypes";
import type { CraftTimelineEntry } from "@/lib/timeline/craft/timelineEntries";
import { toCraftToolCall } from "@/lib/timeline/craft/toolCall";
import type { AcpPlanEntry } from "@/lib/timeline/acp";
import type { TimelineEvent } from "@/lib/timeline/events";
import {
  reduceTimelineEvents,
  type AcpTimelineEntry,
  type TimelineState,
} from "@/lib/timeline/reducer";

interface BuildMessageListProps {
  sessionId: string | null;
  attachmentRefreshKey?: number;
  messages: BuildMessage[];
  /** The current turn's timeline events. */
  timelineEvents: TimelineEvent[];
  isStreaming?: boolean;
  isFinalizing?: boolean;
  /** Whether auto-scroll is enabled (user is at bottom) */
  autoScrollEnabled?: boolean;
  /**
   * Scrollable container wrapping this list. Auto-scroll moves it directly
   * rather than via scrollIntoView, which scrolls every ancestor.
   */
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  /**
   * Trailing content attached to the last assistant block — either the
   * in-progress streaming area (if visible) or the last saved assistant
   * message. Used to render the approval cards inline so they read as
   * part of the agent's last turn instead of a separate message.
   */
  trailingAssistantSlot?: React.ReactNode;
  outputCards?: readonly OutputCard[];
  onOutputOpen?: (output: OutputCard) => void;
  onTurnOutputsOpen?: (turnIndex: number) => void;
  onFileOpen?: (path: string, fileName: string) => void;
}

/**
 * BuildMessageList - Displays the conversation history with FIFO rendering.
 *
 * Per-turn structure after filtering:
 *   [timeline rail of tool calls and thinking], [inline items], [final text]
 * The in-progress turn additionally pins the latest TodoListCard to the top
 * (sticky) and keeps a flashing cursor visible until the turn settles.
 */
export default function BuildMessageList({
  sessionId,
  attachmentRefreshKey = 0,
  messages,
  timelineEvents,
  isStreaming = false,
  isFinalizing = false,
  autoScrollEnabled = true,
  scrollContainerRef,
  trailingAssistantSlot,
  outputCards,
  onOutputOpen,
  onTurnOutputsOpen,
  onFileOpen,
}: BuildMessageListProps) {
  const outputsByTurn = useMemo(() => {
    const groups = new Map<number, OutputCard[]>();
    for (const output of outputCards ?? []) {
      const group = groups.get(output.turn_index);
      if (group) group.push(output);
      else groups.set(output.turn_index, [output]);
    }
    return groups;
  }, [outputCards]);
  const lastAssistantByTurn = useMemo(() => {
    const turns = new Map<number, string>();
    for (const message of messages)
      if (message.type === "assistant" && message.turn_index !== undefined)
        turns.set(message.turn_index, message.id);
    return turns;
  }, [messages]);
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (autoScrollEnabled && container) {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    }
  }, [
    messages.length,
    timelineEvents.length,
    outputCards,
    autoScrollEnabled,
    scrollContainerRef,
  ]);

  // Resolve a connect card's app (oauth-vs-form, credential fields) by ID.
  const { data: connectableApps } = useSWR<ExternalAppUserResponse[]>(
    SWR_KEYS.buildExternalApps,
    errorHandlingFetcher
  );
  const appsById = useMemo(
    () => new Map((connectableApps ?? []).map((app) => [app.id, app])),
    [connectableApps]
  );

  const timelineState = useMemo(
    () => reduceTimelineEvents(timelineEvents),
    [timelineEvents]
  );
  const hasStreamItems =
    timelineState.entries.length > 0 || timelineState.plan.length > 0;
  const lastMessage = messages[messages.length - 1];
  const showStreamingArea =
    hasStreamItems ||
    (isStreaming && (!isFinalizing || lastMessage?.type !== "assistant"));
  const showStreamCursor =
    isStreaming &&
    !timelineState.entries.some(
      (entry) =>
        entry.payload.kind === "message" && entry.status === "streaming"
    );

  // Inline items between timeline steps.
  const renderConnectCard = (
    key: string,
    topMargin: string,
    requestId: string,
    externalAppId: number,
    reason: string | null
  ) => (
    <div key={key} className={cn(topMargin)}>
      <SetupCard
        requestId={requestId}
        externalAppId={externalAppId}
        reason={reason}
        userApp={appsById.get(externalAppId)}
      />
    </div>
  );
  const renderCompaction = (
    key: string,
    topMargin: string,
    summary: string | null
  ) => (
    <div key={key} className={cn(topMargin)}>
      <CompactionMarker summary={summary} />
    </div>
  );
  const renderError = (
    key: string,
    topMargin: string,
    content: string,
    rateLimit: RateLimitDetails | undefined
  ) => {
    if (rateLimit) {
      return (
        <div key={key} className={cn(topMargin)}>
          <ErrorBanner
            error={content}
            errorCode={RATE_LIMITED_ERROR_CODE}
            isRetryable={false}
            details={rateLimit}
          />
        </div>
      );
    }
    return (
      <div
        key={key}
        className={cn(
          topMargin,
          "flex items-start gap-2 rounded-08 border border-status-error-02 bg-status-error-00 px-3 py-2 text-sm text-status-error-05"
        )}
        role="alert"
      >
        <SvgAlertCircle className="mt-0.5 size-4 shrink-0 stroke-status-error-05" />
        <span className="min-w-0 break-words">{content}</span>
      </div>
    );
  };

  // The logo on a header row of its own, for a response that does not start
  // with a run.
  const renderLogoHeader = (key: string) => (
    <TimelineRoot key={key}>
      <TimelineHeaderRow left={<FoldableLogo onyxBranded folded size={24} />} />
    </TimelineRoot>
  );

  /**
   * Renders the in-progress turn from the timeline reducer: runs of thinking
   * and tool calls go on the rail, messages and notices render between them,
   * and the plan is pinned on top.
   */
  const renderTimeline = (
    state: TimelineState,
    opts: { isCurrentStream: boolean }
  ): { nodes: React.ReactNode[]; isEmpty: boolean } => {
    type Block =
      | { kind: "steps"; id: string; entries: CraftTimelineEntry[] }
      | { kind: "item"; entry: AcpTimelineEntry };
    const blocks: Block[] = [];
    for (const entry of state.entries) {
      const step = toCraftStep(entry, opts.isCurrentStream);
      if (step) {
        const last = blocks[blocks.length - 1];
        if (last?.kind === "steps") last.entries.push(step);
        else blocks.push({ kind: "steps", id: step.id, entries: [step] });
      } else if (entry.payload.kind !== "thinking") {
        blocks.push({ kind: "item", entry });
      }
    }

    const todo = planToTodoList(state.plan, opts.isCurrentStream);
    // As in chat, the first run's header carries the logo. Anything else
    // first gets a header row of its own.
    const logoOnRun = blocks[0]?.kind === "steps" && !todo;

    const nodes = blocks.map((block, idx) => {
      if (block.kind === "steps") {
        // The block folds closed once an assistant message follows it.
        const followedByMessage = blocks
          .slice(idx + 1)
          .some((b) => b.kind === "item" && b.entry.payload.kind === "message");
        return (
          <CraftTimeline
            key={block.id}
            entries={block.entries}
            autoCollapse={followedByMessage}
            showAgentAvatar={logoOnRun && idx === 0}
          />
        );
      }

      const topMargin = cn(blocks[idx - 1]?.kind === "steps" && "mt-3", "px-3");
      const { entry } = block;
      switch (entry.payload.kind) {
        case "message":
          return (
            <div key={entry.id} className={cn(topMargin)}>
              <TextChunk
                sessionId={sessionId}
                content={entry.payload.content
                  .map((part) => (part.type === "text" ? part.text : ""))
                  .join("")}
                isStreaming={
                  opts.isCurrentStream && entry.status === "streaming"
                }
                onFileOpen={onFileOpen}
              />
            </div>
          );
        case "notice": {
          const { notice } = entry.payload;
          switch (notice.type) {
            case "connect_app_request":
              return renderConnectCard(
                entry.id,
                topMargin,
                notice.requestId,
                notice.externalAppId,
                notice.reason
              );
            case "compaction":
              return renderCompaction(entry.id, topMargin, notice.summary);
            case "error":
              return renderError(
                entry.id,
                topMargin,
                notice.message || "Turn failed.",
                notice.rateLimit
              );
          }
          return null;
        }
        default:
          return null;
      }
    });

    return {
      nodes: [
        ...(logoOnRun ? [] : [renderLogoHeader("agent-header")]),
        ...(todo
          ? [
              <div key="plan">
                <TodoListCard todoList={todo} defaultOpen={todo.isOpen} />
              </div>,
            ]
          : []),
        ...nodes,
      ],
      isEmpty: blocks.length === 0 && !todo,
    };
  };

  const savedTimelines = useMemo(() => {
    const states = new Map<string, TimelineState>();
    for (const message of messages)
      if (message.type === "assistant" && message.timelineEvents?.length)
        states.set(message.id, reduceTimelineEvents(message.timelineEvents));
    return states;
  }, [messages]);

  const renderAgentMessage = (
    message: BuildMessage,
    trailing?: React.ReactNode
  ) => {
    const turnIndex = message.turn_index;
    const finalizing =
      isFinalizing && !showStreamingArea && message.id === lastMessage?.id;
    const outputs =
      turnIndex === undefined ||
      lastAssistantByTurn.get(turnIndex) !== message.id
        ? undefined
        : outputsByTurn.get(turnIndex);
    const savedTimeline = savedTimelines.get(message.id);
    const savedRender = savedTimeline
      ? renderTimeline(savedTimeline, { isCurrentStream: false })
      : null;
    const visibleSavedRender =
      savedRender && !savedRender.isEmpty ? savedRender : null;

    return (
      <div
        key={message.id}
        className="flex flex-col gap-2 py-4"
        data-testid="craft-assistant-message"
        aria-busy={finalizing}
      >
        <Hoverable.Root group="craftAgentMessage" width="full">
          <div className="flex flex-col gap-2 min-w-0">
            {visibleSavedRender ? (
              visibleSavedRender.nodes
            ) : (
              <>
                {renderLogoHeader("agent-header")}
                <div className="px-3">
                  <TextChunk
                    sessionId={sessionId}
                    content={message.content}
                    onFileOpen={onFileOpen}
                  />
                </div>
              </>
            )}
            {finalizing && (
              <div className="px-3">
                <BlinkingBar />
              </div>
            )}
            {message.content.trim() && (
              <div className="px-3">
                <Hoverable.Item
                  group="craftAgentMessage"
                  variant="appear-on-hover"
                >
                  <CopyButton
                    getCopyText={() =>
                      convertMarkdownTablesToTsv(message.content)
                    }
                    prominence="tertiary"
                    size="sm"
                    data-testid="CraftAgentMessage/copy-button"
                  />
                </Hoverable.Item>
              </div>
            )}
          </div>
        </Hoverable.Root>
        <div className="flex min-w-0 flex-col gap-2 px-3">
          {outputs &&
            onOutputOpen &&
            onTurnOutputsOpen &&
            turnIndex !== undefined && (
              <TurnOutputCards
                outputs={outputs}
                onOpen={onOutputOpen}
                onShowAll={() => onTurnOutputsOpen(turnIndex)}
              />
            )}
          {trailing}
        </div>
      </div>
    );
  };

  // Index of the last saved assistant message — used to anchor the
  // trailingAssistantSlot (e.g. approval cards) when no streaming
  // response is currently in-flight. When streaming, the slot rides
  // along with the streaming area instead.
  const lastAssistantIndex = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i]?.type === "assistant") return i;
    }
    return -1;
  }, [messages]);

  const streamRender = hasStreamItems
    ? renderTimeline(timelineState, { isCurrentStream: true })
    : null;

  return (
    <div className="flex flex-col items-center px-4 pb-4">
      <div className="w-full max-w-[720px] rounded-16 p-4">
        {messages.map((message, idx) => {
          if (message.type === "user") {
            const turnIndex = message.turn_index;
            const outputs =
              turnIndex !== undefined &&
              !(showStreamingArea && idx === messages.length - 1) &&
              !lastAssistantByTurn.has(turnIndex)
                ? outputsByTurn.get(turnIndex)
                : undefined;
            return (
              <div key={message.id}>
                <div className="py-4">
                  {sessionId && message.attachments && (
                    <CraftMessageAttachments
                      sessionId={sessionId}
                      attachments={message.attachments}
                      refreshKey={attachmentRefreshKey}
                      onFileOpen={onFileOpen}
                    />
                  )}
                  <HumanMessage content={message.content} nodeId={idx} />
                </div>
                {outputs &&
                  onOutputOpen &&
                  onTurnOutputsOpen &&
                  turnIndex !== undefined && (
                    <div className="flex flex-col gap-2 py-4">
                      {renderLogoHeader("agent-header")}
                      <div className="min-w-0 px-3">
                        <TurnOutputCards
                          outputs={outputs}
                          onOpen={onOutputOpen}
                          onShowAll={() => onTurnOutputsOpen(turnIndex)}
                        />
                      </div>
                    </div>
                  )}
              </div>
            );
          }
          if (message.type === "assistant") {
            // Anchor the trailing slot (e.g. approval cards) under the
            // last saved assistant message — but only when there's no
            // live streaming area, since that case has its own anchor
            // below.
            const trailing =
              !showStreamingArea && idx === lastAssistantIndex
                ? trailingAssistantSlot
                : null;
            return renderAgentMessage(message, trailing);
          }
          return null;
        })}

        {showStreamingArea && (
          <div
            className="flex flex-col gap-2 py-4"
            data-testid="craft-assistant-message"
            aria-busy={isStreaming}
          >
            {streamRender
              ? streamRender.nodes
              : renderLogoHeader("agent-header")}
            {showStreamCursor && (
              <div className="h-9 flex items-center px-3">
                <BlinkingBar />
              </div>
            )}
            {trailingAssistantSlot}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * A thinking block or tool call as a rail step; anything else is not a step.
 * Outside the current stream, a thinking block that never got its end is done.
 */
function toCraftStep(
  entry: AcpTimelineEntry,
  isCurrentStream: boolean
): CraftTimelineEntry | null {
  switch (entry.payload.kind) {
    case "tool":
      return {
        id: entry.id,
        status: entry.status,
        groupId: null,
        payload: {
          kind: "tool",
          toolCall: toCraftToolCall(entry.payload.toolCall),
        },
      };
    case "thinking":
      if (!entry.payload.text) return null;
      return {
        id: entry.id,
        status:
          !isCurrentStream && entry.status === "streaming"
            ? "done"
            : entry.status,
        groupId: null,
        payload: {
          kind: "thinking",
          content: entry.payload.text,
          isStreaming: isCurrentStream && entry.status === "streaming",
        },
      };
    default:
      return null;
  }
}

/** The plan as the pinned todo list; it starts open only in the live turn. */
function planToTodoList(
  plan: AcpPlanEntry[],
  isOpen: boolean
): TodoListState | null {
  if (plan.length === 0) return null;
  return {
    id: "plan",
    todos: plan.map((entry) => ({
      content: entry.content,
      status: entry.status,
      activeForm: entry._meta?.onyx?.activeForm ?? entry.content,
    })),
    isOpen,
  };
}
