"use client";

import { useRef, useEffect } from "react";
import Logo from "@/refresh-components/Logo";
import TextChunk from "@/app/craft/components/TextChunk";
import ThinkingCard from "@/app/craft/components/ThinkingCard";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { TimelineRoot } from "@/app/app/message/messageComponents/timeline/primitives/TimelineRoot";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import TodoListCard from "@/app/craft/components/TodoListCard";
import WorkingPill from "@/app/craft/components/WorkingPill";
import UserMessage from "@/app/craft/components/UserMessage";
import { BuildMessage } from "@/app/craft/types/streamingTypes";
import {
  StreamItem,
  GroupedStreamItem,
  ToolCallState,
} from "@/app/craft/types/displayTypes";
import { isWorkingToolCall } from "@/app/craft/utils/streamItemHelpers";

/**
 * Group consecutive working tool calls into WorkingGroup items.
 * Keeps text, thinking, todo_list, and task tool_calls as individual items.
 */
function groupStreamItems(items: StreamItem[]): GroupedStreamItem[] {
  const grouped: GroupedStreamItem[] = [];
  let currentWorkingGroup: ToolCallState[] = [];

  const flushWorkingGroup = () => {
    const firstToolCall = currentWorkingGroup[0];
    if (firstToolCall) {
      grouped.push({
        type: "working_group",
        id: `working-${firstToolCall.id}`,
        toolCalls: [...currentWorkingGroup],
      });
      currentWorkingGroup = [];
    }
  };

  for (const item of items) {
    if (item.type === "tool_call" && isWorkingToolCall(item.toolCall)) {
      // Add to current working group
      currentWorkingGroup.push(item.toolCall);
    } else {
      // Flush any accumulated working group before adding non-working item
      flushWorkingGroup();
      // Add the item as-is (text, thinking, todo_list, or task tool_call)
      grouped.push(item as GroupedStreamItem);
    }
  }

  // Don't forget to flush any remaining working group
  flushWorkingGroup();

  return grouped;
}

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
 * BuildMessageList - Displays the conversation history with FIFO rendering
 *
 * User messages are shown as right-aligned bubbles.
 * Agent responses render streamItems in exact chronological order:
 * text, thinking, and tool calls appear exactly as they arrived.
 */
export default function BuildMessageList({
  messages,
  streamItems,
  isStreaming = false,
  autoScrollEnabled = true,
  messagesEndRef: externalMessagesEndRef,
}: BuildMessageListProps) {
  const internalMessagesEndRef = useRef<HTMLDivElement>(null);
  // Use external ref if provided, otherwise use internal ref
  const messagesEndRef = externalMessagesEndRef ?? internalMessagesEndRef;

  // Auto-scroll to bottom when new content arrives (only if auto-scroll is enabled)
  useEffect(() => {
    if (autoScrollEnabled && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length, streamItems.length, autoScrollEnabled, messagesEndRef]);

  // Determine if we should show streaming response area (for current in-progress response)
  const hasStreamItems = streamItems.length > 0;
  const lastMessage = messages[messages.length - 1];
  const lastMessageIsUser = lastMessage?.type === "user";
  // Show streaming area if we have stream items OR if we're waiting for a response to the latest user message
  const showStreamingArea =
    hasStreamItems || (isStreaming && lastMessageIsUser);

  // Helper to render stream items with grouping (used for both saved messages and current streaming)
  const renderStreamItems = (items: StreamItem[], isCurrentStream = false) => {
    const grouped = groupStreamItems(items);

    // Find the index of the last working_group (only relevant for current stream)
    const lastWorkingGroupIndex = isCurrentStream
      ? grouped.findLastIndex((item) => item.type === "working_group")
      : -1;

    return grouped.map((item, index) => {
      switch (item.type) {
        case "text":
          return (
            <TextChunk
              key={item.id}
              content={item.content}
              isStreaming={isCurrentStream && item.isStreaming}
            />
          );
        case "thinking":
          return (
            <ThinkingCard
              key={item.id}
              content={item.content}
              isStreaming={item.isStreaming}
            />
          );
        case "tool_call": {
          // Only task/subagent tools reach here (non-working tools).
          // Tag adjacency so the timeline rail connects contiguous cards
          // rather than rendering each as a lone segment.
          const prev = grouped[index - 1];
          const next = grouped[index + 1];
          const isFirstStep = !prev || prev.type !== "tool_call";
          const isLastStep = !next || next.type !== "tool_call";
          return (
            <CraftToolCard
              key={item.id}
              toolCall={item.toolCall}
              isFirstStep={isFirstStep}
              isLastStep={isLastStep}
            />
          );
        }
        case "todo_list":
          return (
            <TodoListCard
              key={item.id}
              todoList={item.todoList}
              defaultOpen={item.todoList.isOpen}
            />
          );
        case "working_group":
          return (
            <WorkingPill
              key={item.id}
              toolCalls={item.toolCalls}
              isLatest={index === lastWorkingGroupIndex}
            />
          );
        default:
          return null;
      }
    });
  };

  // Helper to render an agent message
  const renderAgentMessage = (message: BuildMessage) => {
    // Check if we have saved stream items in message_metadata
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
            // Render full stream items (includes tool calls, thinking, etc.)
            <TimelineRoot>{renderStreamItems(savedStreamItems)}</TimelineRoot>
          ) : (
            // Fallback to text content only
            <TextChunk content={message.content} />
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col items-center px-4 pb-4">
      <div className="w-full max-w-2xl backdrop-blur-md rounded-16 p-4">
        {/* Render messages in order (user and agent interleaved) */}
        {messages.map((message) =>
          message.type === "user" ? (
            <UserMessage key={message.id} content={message.content} />
          ) : message.type === "assistant" ? (
            renderAgentMessage(message)
          ) : null
        )}

        {/* Render current streaming response (for in-progress response) */}
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

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
