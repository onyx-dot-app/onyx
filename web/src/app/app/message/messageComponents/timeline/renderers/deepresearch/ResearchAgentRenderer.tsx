import React, { useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import { SvgCircle, SvgBookOpen } from "@opal/icons";
import { ResponseItem } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { getToolName } from "@/app/app/message/messageComponents/toolDisplayHelpers";
import { StepContainer } from "@/app/app/message/messageComponents/timeline/StepContainer";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
} from "@/app/app/message/messageComponents/timeline/TimelineRendererComponent";
import { TimelineStepComposer } from "@/app/app/message/messageComponents/timeline/TimelineStepComposer";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import Text from "@/refresh-components/texts/Text";
import {
  processContent,
  useMarkdownComponents,
  renderMarkdown,
} from "@/app/app/message/messageComponents/markdownUtils";
import {
  firstTool,
  isComplete as itemsComplete,
  stringArgument,
  textContent,
  toolMetadata,
} from "@/app/app/services/responseItems";

interface NestedToolGroup {
  sub_turn_index: number;
  toolType: string;
  status: string;
  isComplete: boolean;
  items: ResponseItem[];
}

/** Render child activity and its report within the parent research tool. */
export const ResearchAgentRenderer: MessageRenderer<
  ResponseItem,
  FullChatState
> = ({
  items,
  state,
  onComplete,
  renderType,
  stopPacketSeen,
  isLastStep = true,
  isHover = false,
  children,
}) => {
  const t = useTranslations("chat.messages.timeline");

  const researchTask = stringArgument(firstTool(items), "research_task");

  // Separate parent items from nested tool items
  const { parentItems, nestedToolGroups } = useMemo(() => {
    const parent: ResponseItem[] = [];
    const nestedBySubTurn = new Map<number, ResponseItem[]>();

    items.forEach((item) => {
      if (item.content.kind === "text" && item.content.purpose === "report")
        return;
      const subTurnIndex = item.placement.sub_turn_index;
      if (subTurnIndex === undefined || subTurnIndex === null) {
        parent.push(item);
      } else {
        const group = nestedBySubTurn.get(subTurnIndex) ?? [];
        group.push(item);
        nestedBySubTurn.set(subTurnIndex, group);
      }
    });

    // Convert nested items to groups with metadata
    const groups: NestedToolGroup[] = Array.from(nestedBySubTurn.entries())
      .sort(([a], [b]) => a - b)
      .map(([subTurnIndex, toolItems]) => {
        const name = getToolName(toolItems, t);
        const isComplete = itemsComplete(toolItems);
        return {
          sub_turn_index: subTurnIndex,
          toolType: name,
          status: isComplete ? "Complete" : "Running",
          isComplete,
          items: toolItems,
        };
      });

    return { parentItems: parent, nestedToolGroups: groups };
  }, [items, t]);

  // Filter nested tool groups based on renderType (COMPACT and HIGHLIGHT show only latest)
  const visibleNestedToolGroups = useMemo(() => {
    if (
      (renderType !== RenderType.COMPACT &&
        renderType !== RenderType.HIGHLIGHT) ||
      nestedToolGroups.length === 0
    ) {
      return nestedToolGroups;
    }
    // COMPACT/HIGHLIGHT mode: show only the latest group (last in sorted array)
    const latestGroup = nestedToolGroups[nestedToolGroups.length - 1];
    return latestGroup ? [latestGroup] : [];
  }, [renderType, nestedToolGroups]);

  const isComplete = itemsComplete(parentItems);
  const isReportStreaming = !isComplete && !stopPacketSeen;
  const fullReportContent =
    textContent(items, "report") ||
    toolMetadata(items, "research_result").at(-1)?.intermediate_report ||
    "";

  // Condensed modes: show only the currently active/streaming section
  const isCompact = renderType === RenderType.COMPACT;
  const isHighlight = renderType === RenderType.HIGHLIGHT;
  const isCondensedMode = isCompact || isHighlight;
  // Report takes priority if it has content (means tools are done, report is streaming)
  const showOnlyReport =
    isCondensedMode && fullReportContent && visibleNestedToolGroups.length > 0;
  const showOnlyTools =
    isCondensedMode && !fullReportContent && visibleNestedToolGroups.length > 0;

  // Process content once for consistent markdown handling
  // This ensures code block extraction uses the same offsets as rendered content
  const processedReportContent = useMemo(
    () => processContent(fullReportContent),
    [fullReportContent]
  );

  // Get markdown components for rendering (stable across renders)
  // Uses processed content so code block extraction offsets match rendered content
  const markdownComponents = useMarkdownComponents(
    state,
    processedReportContent,
    "text-text-03 font-main-ui-body"
  );

  // Stable callbacks to avoid creating new functions on every render
  // renderReport renders the processed content
  // Uses pre-computed processedReportContent since ExpandableTextDisplay
  // passes the same fullReportContent that we processed above
  // Parameters are required by ExpandableTextDisplay interface but we use
  // the pre-processed content to ensure offsets match code block extraction
  const renderReport = useCallback(
    (_content: string, _isExpanded?: boolean) =>
      renderMarkdown(
        processedReportContent,
        markdownComponents,
        "text-text-03 font-main-ui-body"
      ),
    [processedReportContent, markdownComponents]
  );

  // HIGHLIGHT mode: return raw content with header embedded in content
  if (isHighlight) {
    if (showOnlyReport) {
      return children([
        {
          icon: null,
          status: null,
          content: (
            <div className="flex flex-col ps-(--timeline-common-text-padding)">
              <Text as="p" text04 mainUiMuted className="mb-1">
                {t("researchAgent.report.title")}
              </Text>
              <ExpandableTextDisplay
                title={t("researchAgent.report.title")}
                content={fullReportContent}
                maxLines={5}
                renderContent={renderReport}
                isStreaming={isReportStreaming}
              />
            </div>
          ),
          supportsCollapsible: true,
          timelineLayout: "content",
        },
      ]);
    }

    if (showOnlyTools) {
      const latestGroup = visibleNestedToolGroups[0];
      if (latestGroup) {
        return (
          <TimelineRendererComponent
            key={latestGroup.sub_turn_index}
            items={latestGroup.items}
            chatState={state}
            animate={!stopPacketSeen && !latestGroup.isComplete}
            stopPacketSeen={stopPacketSeen}
            defaultExpanded={false}
            renderTypeOverride={RenderType.HIGHLIGHT}
            isLastStep={true}
            isHover={isHover}
          >
            {(results: TimelineRendererOutput) =>
              children([
                {
                  icon: null,
                  status: null,
                  content: (
                    <>
                      {results.map((result, index) => (
                        <React.Fragment key={index}>
                          {result.content}
                        </React.Fragment>
                      ))}
                    </>
                  ),
                  supportsCollapsible: true,
                  timelineLayout: "content",
                },
              ])
            }
          </TimelineRendererComponent>
        );
      }
    }

    // Fallback: research task with header embedded
    if (researchTask) {
      return children([
        {
          icon: null,
          status: null,
          content: (
            <div className="flex flex-col ps-(--timeline-common-text-padding)">
              <Text as="p" text04 mainUiMuted>
                {t("researchAgent.task.title")}
              </Text>
              <Text as="p" text03 mainUiMuted>
                {researchTask}
              </Text>
            </div>
          ),
          supportsCollapsible: true,
          timelineLayout: "content",
        },
      ]);
    }

    return children([
      {
        icon: null,
        status: null,
        content: <></>,
        supportsCollapsible: true,
        timelineLayout: "content",
      },
    ]);
  }

  // Build content using StepContainer pattern
  const researchAgentContent = (
    <div className="flex flex-col">
      {/* Research Task - hidden in compact mode when tools/report are active */}
      {researchTask && !showOnlyReport && !showOnlyTools && (
        <StepContainer
          stepIcon={SvgCircle}
          header={t("researchAgent.task.title")}
          collapsible={true}
          isLastStep={
            !stopPacketSeen &&
            nestedToolGroups.length === 0 &&
            !fullReportContent &&
            !isComplete
          }
          isHover={isHover}
        >
          <div className="ps-(--timeline-common-text-padding)">
            <Text as="p" text02 mainUiMuted>
              {researchTask}
            </Text>
          </div>
        </StepContainer>
      )}

      {/* Nested tool calls - hidden when report is streaming in compact mode */}
      {!showOnlyReport &&
        visibleNestedToolGroups.map((group, index) => {
          const isLastNestedStep =
            !stopPacketSeen &&
            index === visibleNestedToolGroups.length - 1 &&
            !fullReportContent &&
            !isComplete;

          return (
            <TimelineRendererComponent
              key={group.sub_turn_index}
              items={group.items}
              chatState={state}
              animate={!stopPacketSeen && !group.isComplete}
              stopPacketSeen={stopPacketSeen}
              defaultExpanded={true}
              isLastStep={isLastNestedStep}
              isHover={isHover}
            >
              {(results: TimelineRendererOutput) => (
                <TimelineStepComposer
                  results={results}
                  isLastStep={isLastNestedStep}
                  isFirstStep={!researchTask && index === 0}
                  isSingleStep={false}
                  collapsible={true}
                />
              )}
            </TimelineRendererComponent>
          );
        })}

      {/* Intermediate report - hidden when tools are active in compact mode */}
      {fullReportContent && !showOnlyTools && (
        <StepContainer
          stepIcon={SvgBookOpen}
          header={t("researchAgent.report.title")}
          isLastStep={!stopPacketSeen && !isComplete}
          isFirstStep={!researchTask && nestedToolGroups.length === 0}
          isHover={isHover}
          noPaddingRight={true}
        >
          <div className="ps-(--timeline-common-text-padding)">
            <ExpandableTextDisplay
              title={t("researchAgent.report.title")}
              content={fullReportContent}
              renderContent={renderReport}
              isStreaming={isReportStreaming}
            />
          </div>
        </StepContainer>
      )}
    </div>
  );

  // Return simplified result (no icon, no status)
  return children([
    {
      icon: null,
      status: null,
      content: researchAgentContent,
      supportsCollapsible: true,
      timelineLayout: "content",
    },
  ]);
};
