"use client";

import { useRef, useEffect, useMemo } from "react";
import { BuildMessage } from "@/app/build/services/buildStreamingModels";
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
 * - Agent activity timeline (tool calls, thinking, plans)
 *
 * Groups messages into display messages and event messages:
 * - Display messages: user messages and assistant messages with content
 * - Event messages: assistant messages with message_metadata (tool calls, thinking, plans)
 */
export default function BuildMessageList({
  messages,
  isStreaming = false,
}: BuildMessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Separate display messages from event messages
  const { displayMessages, eventMessages, hasEventsOnly } = useMemo(() => {
    const display: BuildMessage[] = [];
    const events: BuildMessage[] = [];

    for (const msg of messages) {
      // Event messages have metadata and empty/no content
      if (msg.message_metadata?.type && !msg.content) {
        events.push(msg);
      } else {
        display.push(msg);
      }
    }

    // Check if we have events but no assistant messages with content
    const hasAssistantContent = display.some((m) => m.type === "assistant");
    const hasEventsOnly = events.length > 0 && !hasAssistantContent;

    return { displayMessages: display, eventMessages: events, hasEventsOnly };
  }, [messages]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <div className="flex flex-col items-center px-4 pb-4">
      <div className="w-full max-w-2xl">
        {displayMessages.map((message, index) => {
          const isLastMessage = index === displayMessages.length - 1;
          const isStreamingThis =
            isStreaming && isLastMessage && message.type === "assistant";
          const isLastAssistantMessage =
            message.type === "assistant" && isLastMessage;

          if (message.type === "user") {
            return <UserMessage key={message.id} content={message.content} />;
          }

          // For assistant messages, only show event timeline on the last assistant message
          // This avoids duplicating the timeline for multiple assistant responses
          return (
            <AIMessageWithTools
              key={message.id}
              content={message.content}
              eventMessages={isLastAssistantMessage ? eventMessages : []}
              isStreaming={isStreamingThis}
            />
          );
        })}

        {/* If we have event messages but no assistant message to attach them to, render them */}
        {hasEventsOnly && (
          <AIMessageWithTools
            key="events-only"
            content=""
            eventMessages={eventMessages}
            isStreaming={isStreaming}
          />
        )}

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
