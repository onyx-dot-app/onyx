"use client";

import { useEffect, useMemo } from "react";
import { cn } from "@opal/utils";
import { CopyButton } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgAlertCircle } from "@opal/icons";
import { AnimatePresence, motion } from "motion/react";
import Logo from "@/refresh-components/Logo";
import TextChunk from "@/app/craft/components/TextChunk";
import ThinkingCard from "@/app/craft/components/ThinkingCard";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { convertMarkdownTablesToTsv } from "@/app/app/message/copyingUtils";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import CraftToolGroup from "@/app/craft/components/tool-cards/CraftToolGroup";
import TodoListCard from "@/app/craft/components/TodoListCard";
import HumanMessage from "@/app/app/message/HumanMessage";
import { BuildMessage } from "@/app/craft/types/streamingTypes";
import {
  StreamItem,
  ToolCallState,
  TodoListState,
} from "@/app/craft/types/displayTypes";

/**
 * A render unit: a run of consecutive non-task tool calls (the "Working" block),
 * or a single non-tool item. Task calls become their own one-tool block so they
 * render as standalone, non-collapsible rows.
 */
type RenderBlock =
  | { kind: "tools"; tools: ToolCallState[] }
  | { kind: "item"; item: Exclude<StreamItem, { type: "tool_call" }> };

interface BuildMessageListProps {
  messages: BuildMessage[];
  streamItems: StreamItem[];
  isStreaming?: boolean;
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
}

/**
 * BuildMessageList - Displays the conversation history with FIFO rendering.
 *
 * Per-turn structure after filtering:
 *   [Working block | single tool card], [last thinking?], [final text]
 * The in-progress turn additionally pins the latest TodoListCard to the top
 * (sticky) and surfaces a "working on…" pill at the bottom while a tool is
 * mid-stream.
 */
export default function BuildMessageList({
  messages,
  streamItems,
  isStreaming = false,
  autoScrollEnabled = true,
  scrollContainerRef,
  trailingAssistantSlot,
}: BuildMessageListProps) {
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (autoScrollEnabled && container) {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    }
  }, [
    messages.length,
    streamItems.length,
    autoScrollEnabled,
    scrollContainerRef,
  ]);

  const hasStreamItems = streamItems.length > 0;
  const lastMessage = messages[messages.length - 1];
  const lastMessageIsUser = lastMessage?.type === "user";
  const showStreamingArea =
    hasStreamItems ||
    (isStreaming && (lastMessageIsUser || messages.length === 0));

  const renderStreamItems = (
    rawItems: StreamItem[],
    opts: {
      isCurrentStream: boolean;
      extractLatestTodo: boolean;
    }
  ): { nodes: React.ReactNode[]; pinnedTodo: TodoListState | null } => {
    // Render items in stream order (tools, text, thinking interleaved).
    //
    // Filtering rules that apply first:
    // - Only the LATEST todo_list is kept (either pinned via extractLatestTodo
    //   or rendered inline at its original position).
    // - Thinking remains as a collapsed transcript row so users have a durable
    //   signal that the model spent time reasoning without opening by default.
    let latestTodoIdx = -1;
    rawItems.forEach((it, idx) => {
      if (it.type === "todo_list") latestTodoIdx = idx;
    });

    const items = rawItems.filter((it, idx) => {
      // Collapse to one todo_list per turn.
      if (it.type === "todo_list" && idx !== latestTodoIdx) {
        return false;
      }
      if (opts.extractLatestTodo && it.type === "todo_list") {
        return false;
      }
      return true;
    });

    const pinnedTodo =
      opts.extractLatestTodo && latestTodoIdx !== -1
        ? (
            rawItems[latestTodoIdx] as {
              type: "todo_list";
              todoList: TodoListState;
            }
          ).todoList
        : null;

    // Group the flat items into render blocks: consecutive non-task tool calls
    // merge into one "Working" block; task calls and non-tool items each stand
    // alone.
    const blocks: RenderBlock[] = [];
    for (const it of items) {
      if (it.type !== "tool_call") {
        blocks.push({ kind: "item", item: it });
        continue;
      }
      const tool = it.toolCall;
      const last = blocks[blocks.length - 1];
      if (
        tool.kind !== "task" &&
        last?.kind === "tools" &&
        last.tools[0]!.kind !== "task"
      ) {
        last.tools.push(tool);
      } else {
        blocks.push({ kind: "tools", tools: [tool] });
      }
    }

    const nodes = blocks.map((block, idx) => {
      if (block.kind === "tools") {
        const { tools } = block;
        // A single tool (incl. every task) is a plain, non-collapsible card.
        if (tools.length === 1) {
          return <CraftToolCard key={tools[0]!.id} toolCall={tools[0]!} />;
        }
        // The group folds closed once an assistant message follows it.
        const followedByMessage = blocks
          .slice(idx + 1)
          .some((b) => b.kind === "item" && b.item.type === "text");
        return (
          <CraftToolGroup
            key={`group-${tools[0]!.id}`}
            toolCalls={tools}
            autoCollapse={followedByMessage}
          />
        );
      }

      // Inline item — small top margin when it follows a tool block.
      const topMargin = blocks[idx - 1]?.kind === "tools" ? "mt-3" : "";
      const { item } = block;
      switch (item.type) {
        case "text":
          return (
            <div key={item.id} className={cn(topMargin)}>
              <TextChunk
                content={item.content}
                isStreaming={opts.isCurrentStream && item.isStreaming}
              />
            </div>
          );
        case "thinking":
          return (
            <motion.div
              key={item.id}
              className={cn(topMargin)}
              initial={
                opts.isCurrentStream ? { opacity: 0, y: -4, height: 0 } : false
              }
              animate={{ opacity: 1, y: 0, height: "auto" }}
              exit={{ opacity: 0, y: -6, height: 0, marginTop: 0 }}
              transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            >
              <ThinkingCard
                content={item.content}
                isStreaming={item.isStreaming}
              />
            </motion.div>
          );
        case "todo_list":
          return (
            <div key={item.id} className={cn(topMargin)}>
              <TodoListCard
                todoList={item.todoList}
                defaultOpen={item.todoList.isOpen}
              />
            </div>
          );
        case "error":
          return (
            <div
              key={item.id}
              className={cn(
                topMargin,
                "flex items-start gap-2 rounded-08 border border-status-error-02 bg-status-error-00 px-3 py-2 text-sm text-status-error-05"
              )}
              role="alert"
            >
              <SvgAlertCircle className="mt-0.5 size-4 shrink-0 stroke-status-error-05" />
              <span className="min-w-0 break-words">{item.content}</span>
            </div>
          );
        default:
          return null;
      }
    });

    return { nodes, pinnedTodo };
  };

  const renderAgentMessage = (
    message: BuildMessage,
    trailing?: React.ReactNode
  ) => {
    const savedStreamItems = message.message_metadata?.streamItems as
      | StreamItem[]
      | undefined;
    const savedRender =
      savedStreamItems && savedStreamItems.length > 0
        ? renderStreamItems(savedStreamItems, {
            isCurrentStream: false,
            extractLatestTodo: true,
          })
        : null;
    const visibleSavedRender =
      savedRender && (savedRender.pinnedTodo || savedRender.nodes.length > 0)
        ? savedRender
        : null;

    return (
      <Hoverable.Root key={message.id} group="craftAgentMessage" width="full">
        <div className="flex items-start gap-3 py-4">
          <div className="shrink-0 h-9 flex items-center">
            <Logo onyxBranded folded size={24} />
          </div>
          <div className="flex-1 flex flex-col gap-2 min-w-0">
            {visibleSavedRender ? (
              <>
                {visibleSavedRender.pinnedTodo && (
                  <div>
                    <TodoListCard
                      todoList={visibleSavedRender.pinnedTodo}
                      defaultOpen={visibleSavedRender.pinnedTodo.isOpen}
                    />
                  </div>
                )}
                {visibleSavedRender.nodes}
              </>
            ) : (
              <TextChunk content={message.content} />
            )}
            {message.content.trim() && (
              <Hoverable.Item
                group="craftAgentMessage"
                variant="appear-on-hover"
              >
                <div className="flex flex-row -ml-1">
                  <CopyButton
                    getCopyText={() =>
                      convertMarkdownTablesToTsv(message.content)
                    }
                    prominence="tertiary"
                    data-testid="CraftAgentMessage/copy-button"
                  />
                </div>
              </Hoverable.Item>
            )}
            {trailing}
          </div>
        </div>
      </Hoverable.Root>
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
    ? renderStreamItems(streamItems, {
        isCurrentStream: true,
        extractLatestTodo: true,
      })
    : null;

  return (
    <div className="flex flex-col items-center px-4 pb-4">
      <div className="w-full max-w-[720px] rounded-16 p-4">
        {messages.map((message, idx) => {
          if (message.type === "user") {
            return (
              <div key={message.id} className="py-4">
                <HumanMessage content={message.content} nodeId={idx} />
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
          <div className="flex items-start gap-3 py-4">
            <div className="shrink-0 mt-2">
              <Logo onyxBranded folded size={24} />
            </div>
            <div className="flex-1 flex flex-col gap-2 min-w-0">
              {streamRender?.pinnedTodo && (
                <div>
                  <TodoListCard
                    todoList={streamRender.pinnedTodo}
                    defaultOpen={streamRender.pinnedTodo.isOpen}
                  />
                </div>
              )}
              {!hasStreamItems ? (
                <div className="h-9 flex items-center">
                  <BlinkingBar />
                </div>
              ) : (
                <AnimatePresence initial={false}>
                  {streamRender?.nodes}
                </AnimatePresence>
              )}
              {trailingAssistantSlot}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
