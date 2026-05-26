"use client";

import { Text } from "@opal/components";
import ToolCard from "@/app/craft/components/tool-cards/ToolCard";
import BashBody from "@/app/craft/components/tool-cards/BashBody";
import DiffBody from "@/app/craft/components/tool-cards/DiffBody";
import ReadBody from "@/app/craft/components/tool-cards/ReadBody";
import SearchBody from "@/app/craft/components/tool-cards/SearchBody";
import WebSearchBody from "@/app/craft/components/tool-cards/WebSearchBody";
import WebFetchBody from "@/app/craft/components/tool-cards/WebFetchBody";
import TaskBody from "@/app/craft/components/tool-cards/TaskBody";
import GenericBody from "@/app/craft/components/tool-cards/GenericBody";
import type { ToolCardCommonProps } from "@/app/craft/components/tool-cards/interfaces";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

function renderBody(toolCall: ToolCallState) {
  // toolName takes precedence over kind when it lets us pick a more specific body
  if (toolCall.toolName === "websearch") {
    return <WebSearchBody toolCall={toolCall} />;
  }
  if (toolCall.toolName === "webfetch") {
    return <WebFetchBody toolCall={toolCall} />;
  }

  switch (toolCall.kind) {
    case "execute":
      return <BashBody toolCall={toolCall} />;
    case "edit":
      return <DiffBody toolCall={toolCall} />;
    case "read":
      return <ReadBody toolCall={toolCall} />;
    case "search":
      return <SearchBody toolCall={toolCall} />;
    case "task":
      return <TaskBody toolCall={toolCall} />;
    case "other":
    default:
      return <GenericBody toolCall={toolCall} />;
  }
}

function renderSecondaryLine(toolCall: ToolCallState) {
  if (toolCall.kind === "execute" && toolCall.command) {
    return (
      <Text font="main-ui-mono" color="text-03" nowrap>
        {toolCall.command}
      </Text>
    );
  }
  return undefined;
}

/**
 * CraftToolCard - The single entry point for rendering a tool call in the
 * Craft transcript. Routes to the per-tool body component, wires up the
 * secondary-line (when needed), and forwards density + open state to
 * the ToolCard base.
 */
export default function CraftToolCard({
  toolCall,
  density = "comfortable",
  defaultOpen,
}: ToolCardCommonProps) {
  return (
    <ToolCard
      toolCall={toolCall}
      density={density}
      defaultOpen={defaultOpen}
      secondaryLine={renderSecondaryLine(toolCall)}
      skillName={toolCall.skillName}
    >
      {renderBody(toolCall)}
    </ToolCard>
  );
}
