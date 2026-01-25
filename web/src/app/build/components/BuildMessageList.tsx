"use client";

import { useRef, useEffect } from "react";
import Logo from "@/refresh-components/Logo";
import TextChunk from "@/app/build/components/TextChunk";
import ThinkingCard from "@/app/build/components/ThinkingCard";
import ToolCallPill from "@/app/build/components/ToolCallPill";
import TodoListCard from "@/app/build/components/TodoListCard";
import UserMessage from "@/app/build/components/UserMessage";
import { BuildMessage } from "@/app/build/types/streamingTypes";
import { StreamItem } from "@/app/build/types/displayTypes";

/**
 * BlinkingDot - Pulsing gray circle for loading state
 * Matches the main chat UI's loading indicator
 */
function BlinkingDot() {
  return (
    <span className="animate-pulse flex-none bg-theme-primary-05 inline-block rounded-full h-3 w-3 ml-2 mt-2" />
  );
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
 * Assistant responses render streamItems in exact chronological order:
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

  // Check for active tools (for "Working..." state)
  const hasActiveTools = streamItems.some(
    (item) =>
      item.type === "tool_call" &&
      (item.toolCall.status === "in_progress" ||
        item.toolCall.status === "pending")
  );

  // Helper to render stream items (used for both saved messages and current streaming)
  const renderStreamItems = (items: StreamItem[]) =>
    items.map((item) => {
      switch (item.type) {
        case "text":
          return <TextChunk key={item.id} content={item.content} />;
        case "thinking":
          return (
            <ThinkingCard
              key={item.id}
              content={item.content}
              isStreaming={item.isStreaming}
            />
          );
        case "tool_call":
          return <ToolCallPill key={item.id} toolCall={item.toolCall} />;
        case "todo_list":
          return (
            <TodoListCard
              key={item.id}
              todoList={item.todoList}
              defaultOpen={item.todoList.isOpen}
            />
          );
        default:
          return null;
      }
    });

  // Helper to render an assistant message
  const renderAssistantMessage = (message: BuildMessage) => {
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
            renderStreamItems(savedStreamItems)
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
        {/* Render messages in order (user and assistant interleaved) */}
        {messages.map((message) =>
          message.type === "user" ? (
            <UserMessage key={message.id} content={message.content} />
          ) : message.type === "assistant" ? (
            renderAssistantMessage(message)
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
                // Loading state - no content yet, show blinking dot like main chat
                <BlinkingDot />
              ) : (
                <>
                  {/* Render stream items in FIFO order */}
                  {renderStreamItems(streamItems)}

                  {/* Streaming indicator when actively streaming text */}
                  {isStreaming && hasStreamItems && !hasActiveTools && (
                    <BlinkingDot />
                  )}
                </>
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
