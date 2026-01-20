"use client";

import { useRef, useEffect } from "react";
import {
  BuildMessage,
  ToolCall,
} from "@/app/build/services/buildStreamingModels";
import { useToolCalls } from "@/app/build/hooks/useBuildSessionStore";
import UserMessage from "@/app/build/components/UserMessage";
import AIMessageWithTools from "@/app/build/components/AIMessageWithTools";

interface BuildMessageListProps {
  messages: BuildMessage[];
  isStreaming?: boolean;
}

/**
 * BuildMessageList - Displays the conversation history
 *
 * Shows:
 * - User messages (right-aligned bubbles)
 * - Assistant responses (left-aligned with logo, including tool calls)
 */
export default function BuildMessageList({
  messages,
  isStreaming = false,
}: BuildMessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const toolCalls = useToolCalls();

  // Auto-scroll to bottom when new messages arrive or tool calls update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, toolCalls.length]);

  return (
    <div className="flex flex-col items-center px-4 pb-4">
      <div className="w-full max-w-2xl">
        {messages.map((message, index) => {
          const isLastMessage = index === messages.length - 1;
          const isStreamingThis =
            isStreaming && isLastMessage && message.role === "assistant";

          // Show current tool calls only on the last assistant message while streaming
          const messageToolCalls: ToolCall[] = isStreamingThis
            ? toolCalls
            : message.toolCalls || [];

          if (message.role === "user") {
            return <UserMessage key={message.id} content={message.content} />;
          }

          return (
            <AIMessageWithTools
              key={message.id}
              content={message.content}
              toolCalls={messageToolCalls}
              isStreaming={isStreamingThis}
            />
          );
        })}

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
