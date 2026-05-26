"use client";

import { useRef, useEffect } from "react";
import Logo from "@/refresh-components/Logo";
import TextChunk from "@/app/craft/components/TextChunk";
import ThinkingCard from "@/app/craft/components/ThinkingCard";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { TimelineRoot } from "@/app/app/message/messageComponents/timeline/primitives/TimelineRoot";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import CraftToolGroup from "@/app/craft/components/tool-cards/CraftToolGroup";
import TodoListCard from "@/app/craft/components/TodoListCard";
import UserMessage from "@/app/craft/components/UserMessage";
import { BuildMessage } from "@/app/craft/types/streamingTypes";
import { StreamItem, ToolCallState } from "@/app/craft/types/displayTypes";

interface BuildMessageListProps {
  messages: BuildMessage[];
  streamItems: StreamItem[];
  isStreaming?: boolean;
  /** Whether auto-scroll is enabled (user is at bottom) */
  autoScrollEnabled?: boolean;
  /** Ref to the end marker div for scroll detection */
  messagesEndRef?: React.RefObject<HTMLDivElement>;
}

// Items that render on the timeline rail. Text + todo_list break the rail.
const RAIL_TYPES = new Set<StreamItem["type"]>(["thinking", "tool_call"]);

/**
 * BuildMessageList - Displays the conversation history with FIFO rendering.
 *
 * User messages are right-aligned bubbles. Agent activity (thinking +
 * tool calls + text) renders chronologically inside a single timeline,
 * with the rail connecting contiguous runs of thinking + tool rows.
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

  const renderStreamItems = (items: StreamItem[], isCurrentStream = false) => {
    const nodes: React.ReactNode[] = [];
    let i = 0;
    while (i < items.length) {
      const item = items[i]!;
      const prev = items[i - 1];

      if (item.type === "tool_call") {
        // Consume a contiguous run of tool_calls with the same toolName.
        const groupKey = item.toolCall.toolName ?? item.toolCall.kind;
        const runStart = i;
        const groupTools: ToolCallState[] = [item.toolCall];
        let j = i + 1;
        while (j < items.length) {
          const candidate = items[j]!;
          if (candidate.type !== "tool_call") break;
          const candidateKey =
            candidate.toolCall.toolName ?? candidate.toolCall.kind;
          if (candidateKey !== groupKey) break;
          groupTools.push(candidate.toolCall);
          j++;
        }
        const runEnd = j - 1;
        const after = items[j];
        const isFirstStep = !prev || !RAIL_TYPES.has(prev.type);
        const isLastStep = !after || !RAIL_TYPES.has(after.type);

        if (groupTools.length === 1) {
          nodes.push(
            <CraftToolCard
              key={item.id}
              toolCall={item.toolCall}
              isFirstStep={isFirstStep}
              isLastStep={isLastStep}
            />
          );
        } else {
          nodes.push(
            <CraftToolGroup
              key={`group-${items[runStart]!.id}`}
              toolCalls={groupTools}
              isFirstStep={isFirstStep}
              isLastStep={isLastStep}
            />
          );
        }
        i = runEnd + 1;
        continue;
      }

      const next = items[i + 1];
      const isFirstStep = !prev || !RAIL_TYPES.has(prev.type);
      const isLastStep = !next || !RAIL_TYPES.has(next.type);

      switch (item.type) {
        case "text": {
          const prevIsRail = !!prev && RAIL_TYPES.has(prev.type);
          nodes.push(
            <div key={item.id} className={prevIsRail ? "my-5" : undefined}>
              <TextChunk
                content={item.content}
                isStreaming={isCurrentStream && item.isStreaming}
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
              isFirstStep={isFirstStep}
              isLastStep={isLastStep}
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
    return nodes;
  };

  const renderAgentMessage = (message: BuildMessage) => {
    const savedStreamItems = message.message_metadata?.streamItems as
      | StreamItem[]
      | undefined;

    return (
      <div key={message.id} className="flex items-start gap-3 py-4">
        <div className="shrink-0 mt-0.5">
          <Logo folded size={24} />
        </div>
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          {savedStreamItems && savedStreamItems.length > 0 ? (
            <TimelineRoot>{renderStreamItems(savedStreamItems)}</TimelineRoot>
          ) : (
            <TextChunk content={message.content} />
          )}
        </div>
      </div>
    );
  };

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
            <div className="flex-1 flex flex-col gap-3 min-w-0">
              {!hasStreamItems ? (
                <BlinkingBar addMargin />
              ) : (
                <TimelineRoot>
                  {renderStreamItems(streamItems, true)}
                </TimelineRoot>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
