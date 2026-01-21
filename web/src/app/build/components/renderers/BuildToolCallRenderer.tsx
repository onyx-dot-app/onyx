"use client";

import React from "react";
import { FiCircle } from "react-icons/fi";
import {
  SvgTerminalSmall,
  SvgFileText,
  SvgEdit,
  SvgSettings,
  SvgBubbleText,
} from "@opal/icons";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

const STANDARD_TEXT_COLOR = "text-text-600";

interface ToolCallRendererProps {
  metadata: Record<string, any>;
  isLastItem?: boolean;
  isLoading?: boolean;
}

/**
 * Get the appropriate icon for a tool based on its kind
 */
function getToolIcon(kind: string) {
  const kindLower = kind?.toLowerCase() || "";

  if (kindLower.includes("bash") || kindLower.includes("execute")) {
    return ({ size }: { size: number }) => (
      <SvgTerminalSmall style={{ width: size, height: size }} />
    );
  }
  if (kindLower.includes("write") || kindLower === "edit") {
    return ({ size }: { size: number }) => (
      <SvgEdit style={{ width: size, height: size }} />
    );
  }
  if (kindLower.includes("read")) {
    return ({ size }: { size: number }) => (
      <SvgFileText style={{ width: size, height: size }} />
    );
  }
  if (kindLower.includes("think") || kindLower.includes("thought")) {
    return ({ size }: { size: number }) => (
      <SvgBubbleText style={{ width: size, height: size }} />
    );
  }
  return ({ size }: { size: number }) => (
    <SvgSettings style={{ width: size, height: size }} />
  );
}

/**
 * Extract command from raw_input
 */
function extractCommand(metadata: Record<string, any>): string | null {
  const rawInput = metadata.raw_input;
  if (!rawInput) return null;

  // For bash/execute tools
  if (rawInput.command) return rawInput.command;

  // For file operations
  if (rawInput.file_path || rawInput.path) {
    return rawInput.file_path || rawInput.path;
  }

  // For grep/search
  if (rawInput.pattern) return `pattern: ${rawInput.pattern}`;

  return null;
}

/**
 * Get tool name/title
 */
function getToolName(metadata: Record<string, any>): string {
  // Use title if meaningful
  if (metadata.title && !metadata.title.includes("Running")) {
    return metadata.title;
  }

  const kind = metadata.kind || "";
  const nameMap: Record<string, string> = {
    bash: "Bash",
    write: "Write",
    read: "Read",
    edit: "Edit",
    grep: "Grep",
    glob: "Glob",
  };

  return nameMap[kind.toLowerCase()] || kind || "Tool";
}

/**
 * Renders a single tool call from metadata
 */
export default function BuildToolCallRenderer({
  metadata,
  isLastItem = false,
  isLoading = false,
}: ToolCallRendererProps) {
  const icon = getToolIcon(metadata.kind);
  const toolName = getToolName(metadata);
  const command = extractCommand(metadata);
  const isFailed = metadata.status === "failed";

  console.log("[BuildToolCallRenderer] Rendering tool:", metadata);

  return (
    <div className="relative">
      {!isLastItem && (
        <div
          className="absolute w-px bg-background-tint-04 z-0"
          style={{ left: "10px", top: "20px", bottom: "0" }}
        />
      )}
      <div
        className={cn(
          "flex items-start gap-2",
          STANDARD_TEXT_COLOR,
          "relative z-10"
        )}
      >
        <div className="flex flex-col items-center w-5">
          <div className="flex-shrink-0 flex items-center justify-center w-5 h-5 bg-background rounded-full">
            {icon ? (
              <div className={cn(isLoading && "text-shimmer-base")}>
                {icon({ size: 14 })}
              </div>
            ) : (
              <FiCircle className="w-2 h-2 fill-current text-text-300" />
            )}
          </div>
        </div>
        <div
          className={cn(
            "flex-1 min-w-0 overflow-hidden",
            !isLastItem && "pb-4"
          )}
        >
          <Text
            as="p"
            text02
            className={cn(
              "text-sm mb-1",
              isLoading && !isFailed && "loading-text"
            )}
          >
            {toolName}
          </Text>
          {command && (
            <div className="text-sm text-text-600 overflow-hidden font-mono">
              {command}
            </div>
          )}
          {metadata.error && (
            <div className="text-sm text-red-500 mt-1">{metadata.error}</div>
          )}
        </div>
      </div>
    </div>
  );
}
