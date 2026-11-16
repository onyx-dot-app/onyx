"use client";

import { useTranslations } from "next-intl";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { RunCard } from "@/lib/timeline/components/RunCard";
import { RunStep } from "@/lib/timeline/components/RunStep";
import type { TimelineStepPosition } from "@/lib/timeline/types";
import TaskBody from "@/lib/timeline/craft/components/tool-cards/TaskBody";
import SkillBadge from "@/lib/timeline/craft/components/tool-cards/SkillBadge";
import {
  ThinkingBody,
  splitThinkingTitle,
} from "@/lib/timeline/components/bodies/ThinkingBody";
import {
  getToolCallIcon,
  hasToolCallBody,
  renderToolCallBody,
  renderToolCallHeader,
} from "@/lib/timeline/craft/components/tool-cards/toolCallContent";
import type { CraftTimelineEntry } from "@/lib/timeline/craft/timelineEntries";

/**
 * Agent reasoning separates lines with single newlines, which markdown joins,
 * and runs bold section titles into the text around them. Give each line its
 * own paragraph and each bold title its own block.
 */
function normalizeThinking(text: string): string {
  let out = text.replace(/(?<!\n)\n(?!\n)/g, "\n\n");
  out = out.replace(/([.!?)\]])(\*\*[^*\n]+\*\*)/g, "$1\n\n$2");
  out = out.replace(/(\*\*[^*\n]+\*\*)(?=[A-Z([])/g, "$1\n\n");
  return out;
}

interface CraftTimelineStepProps {
  entry: CraftTimelineEntry;
  position: TimelineStepPosition;
  defaultExpanded: boolean;
}

function CraftTimelineStep({
  entry,
  position,
  defaultExpanded,
}: CraftTimelineStepProps) {
  const t = useTranslations("chat.messages.timeline");
  const { payload } = entry;

  if (payload.kind === "thinking") {
    const { title, remainingContent } = splitThinkingTitle(payload.content);
    const header =
      title ??
      t(
        payload.isStreaming
          ? "header.thinkingEllipsis.label"
          : "header.thinking.label"
      );
    return (
      <RunStep
        // Thinking keeps its own icon while it streams.
        status={entry.status === "streaming" ? "done" : entry.status}
        position={position}
        icon={STEP_ICONS.thinking}
        title={header}
        toggleLabel={header}
        noPaddingRight
        body={
          <ThinkingBody
            content={payload.content}
            displayContent={normalizeThinking(
              title ? remainingContent : payload.content
            )}
            isStreaming={payload.isStreaming}
          />
        }
      />
    );
  }

  const { toolCall } = payload;
  // The task row is its own control: it opens the sub-agent's transcript.
  if (toolCall.kind === "task") {
    return (
      <RunStep
        status={entry.status}
        position={position}
        hideHeader
        body={<TaskBody toolCall={toolCall} />}
      />
    );
  }

  return (
    <RunStep
      status={entry.status}
      position={position}
      icon={getToolCallIcon(toolCall)}
      title={renderToolCallHeader(toolCall)}
      headerAccessory={
        toolCall.skillName && toolCall.toolName !== "skill" ? (
          <SkillBadge name={toolCall.skillName} />
        ) : undefined
      }
      toggleLabel={toolCall.title}
      defaultExpanded={defaultExpanded}
      body={hasToolCallBody(toolCall) ? renderToolCallBody(toolCall) : null}
    />
  );
}

interface CraftTimelineProps {
  /** One run of consecutive tool calls and thinking blocks. */
  entries: CraftTimelineEntry[];
  /** Fold the run closed once an assistant message follows it. */
  autoCollapse?: boolean;
}

/** One run of a Craft turn, on the shared run card. */
export default function CraftTimeline({
  entries,
  autoCollapse = false,
}: CraftTimelineProps) {
  const t = useTranslations("craft.toolCards.group");
  return (
    <RunCard
      steps={entries}
      workingText={t("working.label")}
      autoCollapse={autoCollapse}
      renderStep={(entry, position) => (
        <CraftTimelineStep
          entry={entry}
          position={position}
          defaultExpanded={entries.length === 1 && entry.status === "error"}
        />
      )}
    />
  );
}
