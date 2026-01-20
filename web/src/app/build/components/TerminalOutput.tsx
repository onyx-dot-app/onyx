"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgTerminalSmall, SvgLoader } from "@opal/icons";
import { OutputPacket, OutputPacketType } from "@/app/build/hooks/useBuild";

interface TerminalOutputProps {
  packets: OutputPacket[];
  isStreaming: boolean;
}

/**
 * Get CSS classes for a packet type
 */
function getPacketClasses(type: OutputPacketType): string {
  switch (type) {
    case "message":
      return "text-text-inverted-05";
    case "thought":
      return "text-theme-blue-05 italic";
    case "tool_start":
      return "text-theme-purple-05";
    case "tool_progress":
      return "text-text-inverted-03";
    case "stderr":
      return "text-status-error-05";
    case "stdout":
    default:
      return "text-text-inverted-05";
  }
}

/**
 * Get prefix label for a packet type
 */
function getPacketPrefix(packet: OutputPacket): string {
  switch (packet.type) {
    case "thought":
      return "[Thinking] ";
    case "tool_start":
      return `[Tool: ${packet.toolName || "Unknown"}] `;
    case "tool_progress":
      return "[Result] ";
    default:
      return "";
  }
}

export default function TerminalOutput({
  packets,
  isStreaming,
}: TerminalOutputProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isStreaming && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [packets, isStreaming]);

  return (
    <div className="border border-border-02 rounded-12 overflow-hidden">
      <div className="p-2 bg-background-neutral-01 flex flex-row items-center justify-between gap-2">
        <div className="flex flex-row items-center gap-1.5">
          <SvgTerminalSmall className="size-4 stroke-text-03" />
          <Text mainUiAction text03>
            Output
          </Text>
        </div>
        {isStreaming && (
          <div className="flex flex-row items-center gap-1.5">
            <SvgLoader className="size-4 stroke-status-success-05 animate-spin" />
            <Text secondaryBody className="text-status-success-05">
              Streaming
            </Text>
          </div>
        )}
      </div>
      <div
        ref={containerRef}
        className={cn(
          "p-4 bg-background-neutral-inverted-03 text-text-inverted-05",
          "overflow-auto max-h-96 text-xs"
        )}
        style={{ fontFamily: "var(--font-dm-mono)" }}
      >
        {packets.length === 0 ? (
          <span className="text-text-inverted-03">Waiting for output...</span>
        ) : (
          <div className="flex flex-col gap-2">
            {packets.map((packet, index) => (
              <pre
                key={index}
                className={cn(
                  "whitespace-pre-wrap break-words m-0",
                  getPacketClasses(packet.type)
                )}
              >
                {getPacketPrefix(packet)}
                {packet.content}
              </pre>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
