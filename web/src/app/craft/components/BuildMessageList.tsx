"use client";

import { useRef, useEffect } from "react";
import { cn } from "@opal/utils";
import Logo from "@/refresh-components/Logo";
import TextChunk from "@/app/craft/components/TextChunk";
import ThinkingCard from "@/app/craft/components/ThinkingCard";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import CraftToolGroup from "@/app/craft/components/tool-cards/CraftToolGroup";
import TodoListCard from "@/app/craft/components/TodoListCard";
import UserMessage from "@/app/craft/components/UserMessage";
import { BuildMessage } from "@/app/craft/types/streamingTypes";
import {
  StreamItem,
  ToolCallState,
  TodoListState,
} from "@/app/craft/types/displayTypes";

interface BuildMessageListProps {
  messages: BuildMessage[];
  streamItems: StreamItem[];
  isStreaming?: boolean;
  /** Whether auto-scroll is enabled (user is at bottom) */
  autoScrollEnabled?: boolean;
  /** Ref to the end marker div for scroll detection */
  messagesEndRef?: React.RefObject<HTMLDivElement>;
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
  messagesEndRef: externalMessagesEndRef,
}: BuildMessageListProps) {
  const internalMessagesEndRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = externalMessagesEndRef ?? internalMessagesEndRef;

  useEffect(() => {
    if (autoScrollEnabled && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length, streamItems.length, autoScrollEnabled, messagesEndRef]);

  const hasStreamItems = streamItems.length > 0;
  const lastMessage = messages[messages.length - 1];
  const lastMessageIsUser = lastMessage?.type === "user";
  const showStreamingArea =
    hasStreamItems || (isStreaming && lastMessageIsUser);

  const renderStreamItems = (
    rawItems: StreamItem[],
    opts: { isCurrentStream: boolean; extractLatestTodo: boolean }
  ): { nodes: React.ReactNode[]; pinnedTodo: TodoListState | null } => {
    // Per-turn structure: [Working block, last thinking?, final text].
    // - Drop every settled thinking before the last tool_call (pre-tool narration).
    // - Keep only the last settled thinking, and only if it sits after the last
    //   tool_call (post-tool reasoning; never a hidden pre-tool one that
    //   happened to be the last).
    // - Keep only the LAST text item.
    // - All tool_calls survive; the grouping walker below rolls consecutive
    //   runs into a single "Working" card.
    let lastThinkingIdx = -1;
    let lastToolIdx = -1;
    let lastTextIdx = -1;
    let latestTodoIdx = -1;
    rawItems.forEach((it, idx) => {
      if (it.type === "thinking") lastThinkingIdx = idx;
      if (it.type === "tool_call") lastToolIdx = idx;
      if (it.type === "text") lastTextIdx = idx;
      if (it.type === "todo_list") latestTodoIdx = idx;
    });

    const items = rawItems.filter((it, idx) => {
      if (it.type === "thinking" && !it.isStreaming) {
        if (idx !== lastThinkingIdx) return false;
        if (lastToolIdx > idx) return false;
      }
      if (it.type === "text" && !it.isStreaming && idx !== lastTextIdx) {
        return false;
      }
      // Always collapse to a single todo_list per turn — either pinned at
      // the top of the streaming column, or rendered inline at the latest
      // index for history.
      if (it.type === "todo_list" && idx !== latestTodoIdx) {
        return false;
      }
      if (opts.extractLatestTodo && it.type === "todo_list") {
        return false;
      }
      return true;
    });

    const nodes: React.ReactNode[] = [];
    const pinnedTodo =
      opts.extractLatestTodo && latestTodoIdx !== -1
        ? (
            rawItems[latestTodoIdx] as {
              type: "todo_list";
              todoList: TodoListState;
            }
          ).todoList
        : null;

    let i = 0;
    while (i < items.length) {
      const item = items[i]!;
      const prev = items[i - 1];

      if (item.type === "tool_call") {
        const runStart = i;
        const groupTools: ToolCallState[] = [item.toolCall];
        let j = i + 1;
        while (j < items.length) {
          const candidate = items[j]!;
          if (candidate.type !== "tool_call") break;
          groupTools.push(candidate.toolCall);
          j++;
        }
        const runEnd = j - 1;

        if (groupTools.length === 1) {
          nodes.push(<CraftToolCard key={item.id} toolCall={item.toolCall} />);
        } else {
          nodes.push(
            <CraftToolGroup
              key={`group-${items[runStart]!.id}`}
              toolCalls={groupTools}
            />
          );
        }
        i = runEnd + 1;
        continue;
      }

      const next = items[i + 1];
      const prevIsAgentAction =
        !!prev && (prev.type === "thinking" || prev.type === "tool_call");
      const nextIsAgentAction =
        !!next && (next.type === "thinking" || next.type === "tool_call");

      switch (item.type) {
        case "text": {
          // Visual recession: tool work above the final text should feel like
          // the supporting cast. Add breathing room around the answer.
          nodes.push(
            <div
              key={item.id}
              className={cn(
                prevIsAgentAction && "mt-3",
                nextIsAgentAction && "mb-3"
              )}
            >
              <TextChunk
                content={item.content}
                isStreaming={opts.isCurrentStream && item.isStreaming}
              />
            </div>
          );
          break;
        }
        case "thinking":
          nodes.push(
            <ThinkingCard
              key={item.id}
              content={item.content}
              isStreaming={item.isStreaming}
            />
          );
          break;
        case "todo_list":
          nodes.push(
            <TodoListCard
              key={item.id}
              todoList={item.todoList}
              defaultOpen={item.todoList.isOpen}
            />
          );
          break;
      }
      i++;
    }
    return { nodes, pinnedTodo };
  };

  const renderAgentMessage = (message: BuildMessage) => {
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

    return (
      <div key={message.id} className="flex items-start gap-3 py-4">
        <div className="shrink-0 mt-0.5">
          <Logo folded size={24} />
        </div>
        <div className="flex-1 flex flex-col gap-2 min-w-0">
          {savedRender ? (
            <>
              {savedRender.pinnedTodo && (
                <div className="sticky top-2 z-10">
                  <TodoListCard
                    todoList={savedRender.pinnedTodo}
                    defaultOpen={savedRender.pinnedTodo.isOpen}
                  />
                </div>
              )}
              {savedRender.nodes}
            </>
          ) : (
            <TextChunk content={message.content} />
          )}
        </div>
      </div>
    );
  };

  const streamRender = hasStreamItems
    ? renderStreamItems(streamItems, {
        isCurrentStream: true,
        extractLatestTodo: true,
      })
    : null;

  return (
    <div className="flex flex-col items-center px-4 pb-4">
      <div className="w-full max-w-2xl backdrop-blur-md rounded-16 p-4">
        {messages.map((message) =>
          message.type === "user" ? (
            <UserMessage key={message.id} content={message.content} />
          ) : message.type === "assistant" ? (
            renderAgentMessage(message)
          ) : null
        )}

        {showStreamingArea && (
          <div className="flex items-start gap-3 py-4">
            <div className="shrink-0 mt-0.5">
              <Logo folded size={24} />
            </div>
            <div className="flex-1 flex flex-col gap-2 min-w-0">
              {streamRender?.pinnedTodo && (
                <div className="sticky top-2 z-10">
                  <TodoListCard
                    todoList={streamRender.pinnedTodo}
                    defaultOpen={streamRender.pinnedTodo.isOpen}
                  />
                </div>
              )}
              {!hasStreamItems ? (
                <div className="h-6 flex items-center">
                  <BlinkingBar />
                </div>
              ) : (
                streamRender?.nodes
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
