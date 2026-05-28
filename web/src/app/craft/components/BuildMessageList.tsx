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
    // Render items in the order they streamed: tool calls, text, and thinking
    // appear interleaved instead of all tools first / all text at the bottom.
    // Consecutive tool calls (with no non-tool item between them) are still
    // rolled into a single "Working" CraftToolGroup.
    //
    // Filtering rules that still apply:
    // - Only the LATEST todo_list is kept (either pinned via extractLatestTodo
    //   or rendered inline at its original position).
    // - Settled thinking blocks that occur before a later tool_call are dropped
    //   as pre-tool narration. (Streaming thinkings always pass through.)
    let lastToolIdx = -1;
    let latestTodoIdx = -1;
    rawItems.forEach((it, idx) => {
      if (it.type === "tool_call") lastToolIdx = idx;
      if (it.type === "todo_list") latestTodoIdx = idx;
    });

    const items = rawItems.filter((it, idx) => {
      // Drop settled thinking that's followed by a later tool_call (pre-tool
      // narration that the model has already moved past).
      if (it.type === "thinking" && !it.isStreaming && lastToolIdx > idx) {
        return false;
      }
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

    const nodes: React.ReactNode[] = [];
    let i = 0;
    while (i < items.length) {
      const item = items[i]!;

      if (item.type === "tool_call") {
        // Roll consecutive tool_calls into a single group.
        const groupTools: ToolCallState[] = [item.toolCall];
        let j = i + 1;
        while (j < items.length && items[j]!.type === "tool_call") {
          groupTools.push(
            (items[j]! as Extract<StreamItem, { type: "tool_call" }>).toolCall
          );
          j++;
        }
        if (groupTools.length === 1) {
          nodes.push(<CraftToolCard key={item.id} toolCall={item.toolCall} />);
        } else {
          nodes.push(
            <CraftToolGroup key={`group-${item.id}`} toolCalls={groupTools} />
          );
        }
        i = j;
        continue;
      }

      // Non-tool items render inline in stream order. Add a small top margin
      // when the previous rendered node was a tool group to give the
      // assistant text some breathing room.
      const prev = items[i - 1];
      const followsTool = prev?.type === "tool_call";
      const topMargin = followsTool ? "mt-3" : "";

      switch (item.type) {
        case "text":
          nodes.push(
            <div key={item.id} className={cn(topMargin)}>
              <TextChunk
                content={item.content}
                isStreaming={opts.isCurrentStream && item.isStreaming}
              />
            </div>
          );
          break;
        case "thinking":
          nodes.push(
            <div key={item.id} className={cn(topMargin)}>
              <ThinkingCard
                content={item.content}
                isStreaming={item.isStreaming}
              />
            </div>
          );
          break;
        case "todo_list":
          nodes.push(
            <div key={item.id} className={cn(topMargin)}>
              <TodoListCard
                todoList={item.todoList}
                defaultOpen={item.todoList.isOpen}
              />
            </div>
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
        <div className="shrink-0 mt-2">
          <Logo folded size={24} />
        </div>
        <div className="flex-1 flex flex-col gap-2 min-w-0">
          {savedRender ? (
            <>
              {savedRender.pinnedTodo && (
                <div>
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
      <div className="w-full max-w-2xl rounded-16 p-4">
        {messages.map((message) =>
          message.type === "user" ? (
            <UserMessage key={message.id} content={message.content} />
          ) : message.type === "assistant" ? (
            renderAgentMessage(message)
          ) : null
        )}

        {showStreamingArea && (
          <div className="flex items-start gap-3 py-4">
            <div className="shrink-0 mt-2">
              <Logo folded size={24} />
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
