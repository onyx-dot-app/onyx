"use client";

import { useRef, useEffect } from "react";
import Logo from "@/refresh-components/Logo";
import TextChunk from "@/app/build/components/TextChunk";
import ThinkingCard from "@/app/build/components/ThinkingCard";
import ToolCallPill from "@/app/build/components/ToolCallPill";
import TodoListCard from "@/app/build/components/TodoListCard";
import UserMessage from "@/app/build/components/UserMessage";
import { BuildMessage } from "@/app/build/services/buildStreamingModels";
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
}: BuildMessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, streamItems.length]);

  // Get user messages only (we'll handle assistant content via streamItems)
  const userMessages = messages.filter((msg) => msg.type === "user");

  // Determine if we should show assistant response area
  const hasStreamItems = streamItems.length > 0;
  const hasUserMessages = userMessages.length > 0;
  // Show loading if user sent a message but no response yet (survives navigation)
  const isWaitingForResponse = hasUserMessages && !hasStreamItems;
  const showAssistantArea =
    hasStreamItems || isStreaming || isWaitingForResponse;

  // Check for active tools (for "Working..." state)
  const hasActiveTools = streamItems.some(
    (item) =>
      item.type === "tool_call" &&
      (item.toolCall.status === "in_progress" ||
        item.toolCall.status === "pending")
  );

  return (
    <div className="flex flex-col items-center px-4 pb-4">
      <div className="w-full max-w-2xl backdrop-blur-md rounded-16 p-4">
        {/* Render user messages */}
        {userMessages.map((message) => (
          <UserMessage key={message.id} content={message.content} />
        ))}

        {/* Render assistant response with FIFO stream items */}
        {showAssistantArea && (
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
                  {streamItems.map((item) => {
                    switch (item.type) {
                      case "text":
                        return (
                          <TextChunk key={item.id} content={item.content} />
                        );
                      case "thinking":
                        return (
                          <ThinkingCard
                            key={item.id}
                            content={item.content}
                            isStreaming={item.isStreaming}
                          />
                        );
                      case "tool_call":
                        return (
                          <ToolCallPill
                            key={item.id}
                            toolCall={item.toolCall}
                          />
                        );
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
                  })}

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
