import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { SvgCircle } from "@opal/icons";
import { ResponseItem } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
} from "@/app/app/message/messageComponents/interfaces";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import {
  mutedTextMarkdownComponents,
  collapsedMarkdownComponents,
} from "@/app/app/message/messageComponents/timeline/renderers/sharedMarkdownComponents";
import {
  isComplete as itemsComplete,
  textContent,
} from "@/app/app/services/responseItems";

/**
 * Renderer for deep research plan items.
 * Streams the research plan content with a list icon.
 */
export const DeepResearchPlanRenderer: MessageRenderer<
  ResponseItem,
  FullChatState
> = ({ items, stopPacketSeen, children }) => {
  const t = useTranslations("chat.messages.timeline");
  const isComplete = itemsComplete(items);
  const fullContent = textContent(items, "plan");

  const statusText = isComplete
    ? t("deepResearchPlan.generated.status")
    : t("deepResearchPlan.generating.status");

  // Markdown renderer callback for ExpandableTextDisplay
  // Uses collapsed components (no spacing) in collapsed view, normal spacing in expanded modal
  const renderMarkdown = useCallback(
    (text: string, isExpanded: boolean) => (
      <MinimalMarkdown
        content={text}
        components={
          isExpanded ? mutedTextMarkdownComponents : collapsedMarkdownComponents
        }
      />
    ),
    []
  );

  const planContent = (
    <ExpandableTextDisplay
      title={t("deepResearchPlan.expandable.title")}
      content={fullContent}
      renderContent={renderMarkdown}
      isStreaming={!isComplete}
    />
  );

  return children([
    {
      icon: SvgCircle,
      status: statusText,
      content: planContent,
      noPaddingRight: true,
    },
  ]);
};
