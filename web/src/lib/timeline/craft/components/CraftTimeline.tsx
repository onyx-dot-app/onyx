"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgBubbleText,
  SvgCheckAll,
  SvgExpand,
  SvgFold,
  SvgLoader,
} from "@opal/icons";
import { StepContainer } from "@/lib/timeline/components/StepContainer";
import { TimelineSteps } from "@/lib/timeline/components/TimelineSteps";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
import { TimelineHeaderRow } from "@/lib/timeline/components/primitives/TimelineHeaderRow";
import { groupTimelineEntries } from "@/lib/timeline/entries";
import type { TimelineStepPosition } from "@/lib/timeline/types";
import TaskBody from "@/lib/timeline/craft/components/tool-cards/TaskBody";
import SkillBadge from "@/lib/timeline/craft/components/tool-cards/SkillBadge";
import ThinkingMarkdown from "@/lib/timeline/craft/components/ThinkingMarkdown";
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
    const header = t(
      payload.isStreaming
        ? "header.thinkingEllipsis.label"
        : "header.thinking.label"
    );
    return (
      <StepContainer
        stepIcon={SvgBubbleText}
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
          <ThinkingMarkdown
            content={payload.content}
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
}

/**
 * CraftTimeline renders one run of a Craft turn's tool calls and thinking on
 * the shared timeline rail. A run with more than one entry gets a "Working"
 * header that folds it.
 */
export default function CraftTimeline({
  entries,
  autoCollapse = false,
}: CraftTimelineProps) {
  const t = useTranslations("craft.toolCards.group");
  const tTimeline = useTranslations("chat.messages.timeline");
  const groups = useMemo(() => groupTimelineEntries(entries), [entries]);
  const isRunning = entries.some((entry) => entry.status === "streaming");
  const foldable = entries.length > 1;
  // Open while the run is active so streaming steps stay visible; settled
  // runs start folded.
  const [isOpen, setIsOpen] = useState(!foldable || isRunning);

  // Fold closed once a message follows; fire once so a manual re-open sticks.
  const didAutoCollapse = useRef(false);
  useEffect(() => {
    if (foldable && autoCollapse && !didAutoCollapse.current) {
      didAutoCollapse.current = true;
      setIsOpen(false);
    }
  }, [foldable, autoCollapse]);

  const toolCount = entries.filter(
    (entry) => entry.payload.kind === "tool"
  ).length;

  return (
    <TimelineRoot>
      {foldable && (
        <TimelineHeaderRow
          left={
            isRunning ? (
              <SvgLoader className="size-4 stroke-status-info-05 animate-spin" />
            ) : (
              <SvgCheckAll className="size-4 stroke-text-03" />
            )
          }
        >
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
            gap={2}
            padding={1}
          >
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={2}
              width="fit"
            >
              <Text font="main-ui-muted" color="text-04">
                {t("working.label")}
              </Text>
              {toolCount > 0 && (
                <Badge
                  title={t("calls.tag", { count: toolCount })}
                  size={4}
                  color="default"
                />
              )}
            </Section>
            <Button
              prominence="tertiary"
              size="md"
              icon={isOpen ? SvgFold : SvgExpand}
              onClick={() => setIsOpen((prev) => !prev)}
              aria-expanded={isOpen}
              aria-label={tTimeline(
                isOpen ? "collapseButton.ariaLabel" : "expandButton.ariaLabel"
              )}
            />
          </Section>
        </TimelineHeaderRow>
      )}
      {isOpen && (
        <TimelineSteps
          groups={groups}
          renderEntry={(entry, position) => (
            <CraftTimelineStep
              entry={entry}
              position={position}
              defaultExpanded={!foldable && entry.status === "error"}
            />
          )}
        />
      )}
    </TimelineRoot>
  );
}
