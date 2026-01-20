"use client";

import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import {
  SvgChevronDown,
  SvgChevronRight,
  SvgTerminalSmall,
  SvgCheckCircle,
  SvgLoader,
  SvgAlertCircle,
  SvgFileText,
  SvgCode,
  SvgEdit,
  SvgGlobe,
} from "@opal/icons";
import { useState } from "react";

export interface OutputItem {
  type:
    | "text"
    | "tool_call"
    | "tool_output"
    | "tool_result"
    | "thinking"
    | "status"
    | "error";
  content: string;
  toolName?: string;
  toolType?: string;
  description?: string;
  isComplete?: boolean;
  timestamp: number;
}

interface BuildMessageProps {
  items: OutputItem[];
  isStreaming: boolean;
}

// Get icon based on tool type
function getToolIcon(toolType?: string) {
  switch (toolType?.toLowerCase()) {
    case "bash":
      return SvgTerminalSmall;
    case "read":
      return SvgFileText;
    case "write":
    case "edit":
      return SvgEdit;
    case "web":
    case "fetch":
      return SvgGlobe;
    default:
      return SvgCode;
  }
}

// Get a friendly label for the tool
function getToolLabel(toolType?: string, toolName?: string): string {
  if (toolName) return toolName;
  switch (toolType?.toLowerCase()) {
    case "bash":
      return "Running command";
    case "read":
      return "Reading file";
    case "write":
      return "Writing file";
    case "edit":
      return "Editing file";
    default:
      return "Using tool";
  }
}

interface ToolCallBubbleProps {
  item: OutputItem;
  isStreaming: boolean;
}

function ToolCallBubble({ item, isStreaming }: ToolCallBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const isComplete = item.isComplete ?? !isStreaming;
  const Icon = getToolIcon(item.toolType);
  const label = getToolLabel(item.toolType, item.toolName);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <button
          className={cn(
            "inline-flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-full",
            "border transition-all text-left",
            isComplete
              ? "bg-background-neutral-01 border-border-02 hover:bg-background-neutral-02"
              : "bg-status-info-01 border-status-info-02"
          )}
        >
          {isStreaming && !isComplete ? (
            <SvgLoader className="size-3.5 stroke-status-info-05 animate-spin shrink-0" />
          ) : (
            <Icon className="size-3.5 stroke-text-03 shrink-0" />
          )}
          <span className="text-xs font-medium text-text-04">
            {item.toolType || "Tool"}
          </span>
          <span className="text-xs text-text-03 truncate max-w-[200px]">
            {item.description || label}
          </span>
          {isComplete && (
            <SvgCheckCircle className="size-3.5 stroke-status-success-05 shrink-0 ml-0.5" />
          )}
          {isOpen ? (
            <SvgChevronDown className="size-3 stroke-text-03 shrink-0" />
          ) : (
            <SvgChevronRight className="size-3 stroke-text-03 shrink-0" />
          )}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div
          className={cn(
            "mt-2 p-3 rounded-08 border border-border-01",
            "bg-background-neutral-inverted-03 text-text-inverted-05",
            "text-xs overflow-x-auto max-h-48 overflow-y-auto"
          )}
          style={{ fontFamily: "var(--font-dm-mono)" }}
        >
          <pre className="whitespace-pre-wrap break-words m-0">
            {item.content || "Waiting for output..."}
          </pre>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

interface TextItemProps {
  content: string;
}

function TextItem({ content }: TextItemProps) {
  return (
    <div className="py-1">
      <MinimalMarkdown content={content} className="text-text-05" />
    </div>
  );
}

interface ThinkingItemProps {
  content: string;
}

function ThinkingItem({ content }: ThinkingItemProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <button
          className={cn(
            "inline-flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-full",
            "border border-theme-blue-02 bg-theme-blue-01 hover:bg-theme-blue-02",
            "transition-all text-left"
          )}
        >
          <span className="text-xs font-medium text-theme-blue-05">
            Thinking
          </span>
          <span className="text-xs text-theme-blue-04 truncate max-w-[200px]">
            {content.slice(0, 50)}
            {content.length > 50 ? "..." : ""}
          </span>
          {isOpen ? (
            <SvgChevronDown className="size-3 stroke-theme-blue-05 shrink-0" />
          ) : (
            <SvgChevronRight className="size-3 stroke-theme-blue-05 shrink-0" />
          )}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div
          className={cn(
            "mt-2 p-3 rounded-08 border border-theme-blue-02",
            "bg-theme-blue-01 text-theme-blue-05",
            "text-xs overflow-x-auto max-h-48 overflow-y-auto italic"
          )}
        >
          <p className="whitespace-pre-wrap break-words m-0">{content}</p>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

interface ToolResultItemProps {
  content: string;
}

function ToolResultItem({ content }: ToolResultItemProps) {
  // Truncate very long results
  const displayContent =
    content.length > 500 ? content.slice(0, 500) + "..." : content;

  return (
    <div
      className={cn(
        "p-2 rounded-08 border border-border-01",
        "bg-background-neutral-01 text-text-03",
        "text-xs overflow-x-auto max-h-32 overflow-y-auto"
      )}
      style={{ fontFamily: "var(--font-dm-mono)" }}
    >
      <pre className="whitespace-pre-wrap break-words m-0">
        {displayContent}
      </pre>
    </div>
  );
}

interface StatusItemProps {
  content: string;
  isError?: boolean;
}

function StatusItem({ content, isError }: StatusItemProps) {
  return (
    <div
      className={cn(
        "inline-flex flex-row items-center gap-2 px-3 py-1.5 rounded-full",
        isError
          ? "bg-status-error-01 text-status-error-05"
          : "bg-status-success-01 text-status-success-05"
      )}
    >
      {isError ? (
        <SvgAlertCircle className="size-4 shrink-0" />
      ) : (
        <SvgCheckCircle className="size-4 shrink-0" />
      )}
      <Text secondaryBody>{content}</Text>
    </div>
  );
}

export default function BuildMessage({
  items,
  isStreaming,
}: BuildMessageProps) {
  if (items.length === 0 && !isStreaming) {
    return null;
  }

  return (
    <div className="flex items-start gap-3 py-4">
      <div className="shrink-0 mt-0.5">
        <Logo folded size={24} />
      </div>
      <div className="flex-1 flex flex-col gap-2 min-w-0">
        {items.length === 0 && isStreaming ? (
          <div className="flex items-center gap-2 py-1">
            <SvgLoader className="size-4 stroke-text-03 animate-spin" />
            <Text secondaryBody text03>
              Thinking...
            </Text>
          </div>
        ) : (
          items.map((item, index) => {
            switch (item.type) {
              case "text":
                return <TextItem key={index} content={item.content} />;
              case "thinking":
                return <ThinkingItem key={index} content={item.content} />;
              case "tool_call":
              case "tool_output":
                return (
                  <ToolCallBubble
                    key={index}
                    item={item}
                    isStreaming={isStreaming}
                  />
                );
              case "tool_result":
                return <ToolResultItem key={index} content={item.content} />;
              case "status":
                return <StatusItem key={index} content={item.content} />;
              case "error":
                return (
                  <StatusItem key={index} content={item.content} isError />
                );
              default:
                return null;
            }
          })
        )}
      </div>
    </div>
  );
}
