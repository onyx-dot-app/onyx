"use client";

import { useRef, useEffect } from "react";
import { BuildMessage } from "@/app/build/services/buildStreamingModels";
import UserMessage from "@/app/build/components/UserMessage";
import AIMessageSimple from "@/app/build/components/AIMessageSimple";

interface BuildMessageListProps {
  messages: BuildMessage[];
  isStreaming?: boolean;
}

/**
 * BuildMessageList - Displays the conversation history
 *
 * Shows:
 * - User messages (right-aligned bubbles)
 * - Assistant responses (left-aligned with logo)
 */
export default function BuildMessageList({
  messages,
  isStreaming = false,
}: BuildMessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <div className="flex flex-col items-center px-4 pb-4">
      <div className="w-full max-w-2xl">
        {messages.map((message, index) => {
          const isLastMessage = index === messages.length - 1;
          const isStreamingThis =
            isStreaming && isLastMessage && message.role === "assistant";

          if (message.role === "user") {
            return <UserMessage key={message.id} content={message.content} />;
          }

          return (
            <AIMessageSimple
              key={message.id}
              content={message.content}
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
