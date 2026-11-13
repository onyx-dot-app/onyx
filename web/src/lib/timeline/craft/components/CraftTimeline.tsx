"use client";

import { TIMELINE_HEADER_ICON_PX } from "@/lib/timeline/components/primitives/tokens";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { SvgCircle, SvgCheckCircle, SvgStopCircle } from "@opal/icons";
import { FoldableLogo } from "@/lib/app/components";
import { StepContainer } from "@/lib/timeline/components/StepContainer";
import { TimelineSteps } from "@/lib/timeline/components/TimelineSteps";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
import { RunHeaderRow } from "@/lib/timeline/components/primitives/TimelineHeaderRow";
import { StreamingHeader } from "@/lib/timeline/components/headers/StreamingHeader";
import { CompletedHeader } from "@/lib/timeline/components/headers/CompletedHeader";
import { StoppedHeader } from "@/lib/timeline/components/headers/StoppedHeader";
import { groupTimelineEntries } from "@/lib/timeline/entries";
import type { TimelineStepPosition } from "@/lib/timeline/types";
import TaskBody from "@/lib/timeline/craft/components/tool-cards/TaskBody";
import SkillBadge from "@/lib/timeline/craft/components/tool-cards/SkillBadge";
import {
  ThinkingBody,
  splitThinkingTitle,
} from "@/lib/timeline/components/bodies/ThinkingBody";
import {
  getToolCallStepIcon,
  hasToolCallBody,
  renderToolCallBody,
  renderToolCallHeader,
} from "@/lib/timeline/craft/components/tool-cards/toolCallContent";
import type { CraftTimelineEntry } from "@/lib/timeline/craft/timelineEntries";

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
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const toggle = () => setIsExpanded((prev) => !prev);
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
      <StepContainer
        stepIcon={SvgCircle}
        header={header}
        toggleLabel={header}
        isExpanded={isExpanded}
        onToggle={toggle}
        supportsCollapsible
        isFirstStep={position.isFirst}
        isLastStep={position.isLast}
        noPaddingRight
      >
        {isExpanded ? (
          <ThinkingBody
            content={payload.content}
            displayContent={title ? remainingContent : payload.content}
            isStreaming={payload.isStreaming}
          />
        ) : null}
      </StepContainer>
    );
  }

  const { toolCall } = payload;
  // The task row is its own control: it opens the sub-agent's transcript.
  if (toolCall.kind === "task") {
    return (
      <StepContainer
        hideHeader
        isFirstStep={position.isFirst}
        isLastStep={position.isLast}
      >
        <TaskBody toolCall={toolCall} />
      </StepContainer>
    );
  }

  const failed = entry.status === "error";
  // Failed calls stay expandable so the error is reachable.
  const expandable = hasToolCallBody(toolCall) || failed;
  return (
    <StepContainer
      stepIcon={getToolCallStepIcon(toolCall)}
      header={
        <span className="block truncate">{renderToolCallHeader(toolCall)}</span>
      }
      headerAccessory={
        toolCall.skillName && toolCall.toolName !== "skill" ? (
          <SkillBadge name={toolCall.skillName} />
        ) : undefined
      }
      toggleLabel={toolCall.title}
      isExpanded={isExpanded}
      onToggle={toggle}
      supportsCollapsible={expandable}
      isFirstStep={position.isFirst}
      isLastStep={position.isLast}
      surfaceBackground={failed ? "error" : undefined}
    >
      {expandable && isExpanded ? renderToolCallBody(toolCall) : null}
    </StepContainer>
  );
}

interface CraftTimelineProps {
  /** One run of consecutive tool calls and thinking blocks. */
  entries: CraftTimelineEntry[];
  /** Fold the run closed once an assistant message follows it. */
  autoCollapse?: boolean;
  /** Only a response's first run shows the agent's logo, as in chat. */
  showAgentAvatar?: boolean;
}

/**
 * CraftTimeline renders one run of a Craft turn's tool calls and thinking on
 * the shared timeline rail, under the shared run header. A run with more
 * than one entry folds, and shows a Done or Stopped row when expanded.
 */
export default function CraftTimeline({
  entries,
  autoCollapse = false,
  showAgentAvatar = false,
}: CraftTimelineProps) {
  const t = useTranslations("craft.toolCards.group");
  const tTimeline = useTranslations("chat.messages.timeline");
  const groups = useMemo(() => groupTimelineEntries(entries), [entries]);
  const isRunning = entries.some((entry) => entry.status === "streaming");
  const isStopped =
    !isRunning && entries.some((entry) => entry.status === "stopped");
  const foldable = entries.length > 1;
  // Open while the run is active so streaming steps stay visible; settled
  // runs start folded.
  const [isOpen, setIsOpen] = useState(!foldable || isRunning);
  const toggle = () => setIsOpen((prev) => !prev);

  // Fold closed once a message follows; fire once so a manual re-open sticks.
  const didAutoCollapse = useRef(false);
  useEffect(() => {
    if (foldable && autoCollapse && !didAutoCollapse.current) {
      didAutoCollapse.current = true;
      setIsOpen(false);
    }
  }, [foldable, autoCollapse]);

  // A run that streams here is timed; a saved run has no duration.
  const [startedAt] = useState<number | undefined>(() =>
    isRunning ? Date.now() : undefined
  );
  const [durationSeconds, setDurationSeconds] = useState(0);
  useEffect(() => {
    if (!isRunning && startedAt !== undefined) {
      setDurationSeconds(
        Math.max(1, Math.round((Date.now() - startedAt) / 1000))
      );
    }
  }, [isRunning, startedAt]);

  const showEndRow = foldable && isOpen && !isRunning;

  return (
    <TimelineRoot>
      <RunHeaderRow
        left={
          showAgentAvatar ? (
            <FoldableLogo onyxBranded folded size={TIMELINE_HEADER_ICON_PX} />
          ) : null
        }
        interactive={foldable}
        tinted={isRunning || isOpen}
        roundedBottom={!isOpen}
      >
        {isRunning ? (
          <StreamingHeader
            headerText={t("working.label")}
            collapsible={foldable}
            isExpanded={isOpen}
            onToggle={toggle}
            streamingStartTime={startedAt}
          />
        ) : isStopped ? (
          <StoppedHeader
            totalSteps={entries.length}
            collapsible={foldable}
            isExpanded={isOpen}
            onToggle={toggle}
          />
        ) : (
          <CompletedHeader
            totalSteps={entries.length}
            collapsible={foldable}
            isExpanded={isOpen}
            onToggle={toggle}
            processingDurationSeconds={durationSeconds}
          />
        )}
      </RunHeaderRow>
      {isOpen && (
        <TimelineSteps
          groups={groups}
          renderEntry={(entry, position) => (
            <CraftTimelineStep
              entry={entry}
              position={{ ...position, isLast: position.isLast && !showEndRow }}
              defaultExpanded={!foldable && entry.status === "error"}
            />
          )}
        />
      )}
      {showEndRow && (
        <StepContainer
          stepIcon={isStopped ? SvgStopCircle : SvgCheckCircle}
          header={tTimeline(
            isStopped ? "stoppedStep.header" : "doneStep.header"
          )}
          isLastStep
          isFirstStep={false}
        >
          {null}
        </StepContainer>
      )}
    </TimelineRoot>
  );
}
