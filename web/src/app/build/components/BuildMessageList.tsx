"use client";

import { useRef, useEffect } from "react";
import Text from "@/refresh-components/texts/Text";

/**
 * BuildMessageList - Displays the conversation history
 *
 * Shows:
 * - User messages
 * - Assistant responses with tool calls
 * - Status messages
 * - Error messages
 *
 * TODO: Connect to useBuildSession hook for message data
 */
export default function BuildMessageList() {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  // TODO: Get messages from useBuildSession hook
  const isRunning = false;

  return (
    <div className="flex flex-col items-center px-4 pb-4">
      <div className="w-full max-w-2xl">
        {/* Placeholder - will be populated via useBuildSession hook */}
        <div className="py-8 text-center">
          <Text secondaryBody text03>
            {isRunning
              ? "Processing your request..."
              : "Send a message to start building"}
          </Text>
        </div>

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
