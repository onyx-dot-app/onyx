"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useBuild, OutputPacket } from "@/app/build/hooks/useBuild";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import Message from "@/refresh-components/messages/Message";
import BuildInputBar, { BuildInputBarHandle } from "./components/BuildInputBar";
import BuildMessage, { OutputItem } from "./components/BuildMessage";
import UserMessage from "./components/UserMessage";
import BuildSidePanel from "./components/BuildSidePanel";
import { SvgSidebar } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";

interface ChatMessage {
  id: string;
  type: "user" | "assistant";
  content: string;
  outputItems?: OutputItem[];
  timestamp: number;
}

function parseOutputPackets(packets: OutputPacket[]): OutputItem[] {
  const items: OutputItem[] = [];

  // Combine all packet content first
  const fullContent = packets.map((p) => p.content).join("");

  // Regex to match tool calls inline: [Tool: ToolName] {json}
  // This handles JSON with nested braces by matching balanced braces
  const toolPattern =
    /\[Tool:\s*(\w+)\]\s*(\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})/g;

  let lastIndex = 0;
  let match;

  while ((match = toolPattern.exec(fullContent)) !== null) {
    // Add any text before this tool call
    const textBefore = fullContent.slice(lastIndex, match.index).trim();
    if (textBefore) {
      items.push({
        type: "text",
        content: textBefore,
        timestamp: Date.now(),
      });
    }

    const toolType = match[1] || "Tool";
    const jsonStr = match[2] || "{}";
    let description = "";

    // Try to parse JSON for description
    try {
      const json = JSON.parse(jsonStr);
      description =
        json.description ||
        json.command ||
        json.file_path ||
        json.content ||
        "";
      // Truncate long descriptions
      if (description.length > 100) {
        description = description.substring(0, 100) + "...";
      }
    } catch {
      // If JSON parsing fails, use a portion of the raw string
      description =
        jsonStr.length > 50 ? jsonStr.substring(0, 50) + "..." : jsonStr;
    }

    items.push({
      type: "tool_call",
      content: jsonStr,
      toolType: toolType,
      description: description,
      isComplete: true,
      timestamp: Date.now(),
    });

    lastIndex = match.index + match[0].length;
  }

  // Add any remaining text after the last tool call
  const remainingText = fullContent.slice(lastIndex).trim();
  if (remainingText) {
    items.push({
      type: "text",
      content: remainingText,
      timestamp: Date.now(),
    });
  }

  return items;
}

export default function BuildPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sidePanelOpen, setSidePanelOpen] = useState(true);
  const inputRef = useRef<BuildInputBarHandle>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { status, sessionId, packets, artifacts, error, run, cleanup } =
    useBuild();

  const hasMessages = messages.length > 0;
  const webappArtifact = artifacts.find((a) => a.artifact_type === "webapp");
  const isRunning = status === "running" || status === "creating";

  // Convert packets to output items for the current assistant message
  const currentOutputItems = parseOutputPackets(packets);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, packets]);

  const handleSubmit = useCallback(
    async (message: string) => {
      // Add user message
      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        type: "user",
        content: message,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, userMessage]);

      // Start the build
      await run(message);
    },
    [run]
  );

  // When the build completes, add the assistant message
  useEffect(() => {
    if (status === "completed" || status === "failed") {
      const outputItems = parseOutputPackets(packets);

      if (status === "completed") {
        outputItems.push({
          type: "status",
          content: "Task completed successfully",
          timestamp: Date.now(),
        });
      }

      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        type: "assistant",
        content: "",
        outputItems,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    }
  }, [status]);

  const handleCleanup = useCallback(async () => {
    await cleanup();
    setMessages([]);
  }, [cleanup]);

  return (
    <div className="flex h-screen">
      {/* Left panel - Chat */}
      <div
        className={cn(
          "flex flex-col h-full transition-all duration-300",
          sidePanelOpen && sessionId ? "w-1/2" : "w-full"
        )}
      >
        {/* Chat header */}
        <div className="flex flex-row items-center justify-between px-4 py-3 border-b border-border-01">
          <div className="flex flex-row items-center gap-2">
            <Logo folded size={24} />
            <Text headingH3 text05>
              Build
            </Text>
          </div>
          <div className="flex flex-row items-center gap-2">
            {sessionId && (
              <>
                <button
                  onClick={handleCleanup}
                  className="px-3 py-1.5 text-sm rounded-08 text-status-error-05 hover:bg-status-error-01 transition-colors"
                >
                  Clear session
                </button>
                <IconButton
                  icon={SvgSidebar}
                  onClick={() => setSidePanelOpen(!sidePanelOpen)}
                  tertiary
                  tooltip={sidePanelOpen ? "Hide panel" : "Show panel"}
                />
              </>
            )}
          </div>
        </div>

        {/* Chat messages area */}
        <div className="flex-1 overflow-auto">
          {!hasMessages ? (
            /* Welcome state - centered */
            <div className="h-full flex flex-col items-center justify-center px-4">
              <div className="flex flex-col items-center gap-4 mb-8">
                <Logo folded size={48} />
                <Text headingH2 text05>
                  What would you like to build?
                </Text>
                <Text secondaryBody text03 className="text-center max-w-md">
                  Describe your task and I'll execute it in an isolated
                  environment. You can build web apps, run scripts, process
                  data, and more.
                </Text>
              </div>
              <div className="w-full max-w-2xl">
                <BuildInputBar
                  ref={inputRef}
                  onSubmit={handleSubmit}
                  isRunning={isRunning}
                  placeholder="Create a React app that shows a dashboard..."
                />
              </div>
            </div>
          ) : (
            /* Messages list */
            <div className="flex flex-col items-center px-4 pb-4">
              <div className="w-full max-w-2xl">
                {messages.map((message) => (
                  <div key={message.id}>
                    {message.type === "user" ? (
                      <UserMessage content={message.content} />
                    ) : (
                      <BuildMessage
                        items={message.outputItems || []}
                        isStreaming={false}
                      />
                    )}
                  </div>
                ))}

                {/* Streaming assistant message */}
                {isRunning && (
                  <BuildMessage items={currentOutputItems} isStreaming={true} />
                )}

                {/* Error message */}
                {error && (
                  <div className="py-4">
                    <Message
                      error
                      text={error}
                      description="An error occurred during task execution"
                      onClose={() => {}}
                      close={false}
                    />
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            </div>
          )}
        </div>

        {/* Input bar at bottom when messages exist */}
        {hasMessages && (
          <div className="px-4 pb-4 pt-2 border-t border-border-01">
            <div className="max-w-2xl mx-auto">
              <BuildInputBar
                ref={inputRef}
                onSubmit={handleSubmit}
                isRunning={isRunning}
                placeholder="Continue the conversation..."
              />
            </div>
          </div>
        )}
      </div>

      {/* Right panel - Side panel */}
      {sidePanelOpen && sessionId && (
        <div className="w-1/2 border-l border-border-01 h-full">
          <BuildSidePanel
            sessionId={sessionId}
            artifacts={artifacts}
            hasWebapp={!!webappArtifact}
            onClose={() => setSidePanelOpen(false)}
          />
        </div>
      )}
    </div>
  );
}
