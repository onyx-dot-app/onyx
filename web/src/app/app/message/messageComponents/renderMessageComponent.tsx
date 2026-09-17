import { JSX, memo } from "react";
import { StopReason, ResponseItem } from "@/app/app/services/streamingModels";
import {
  FullChatState,
  MessageRenderer,
  RenderType,
  RendererOutput,
} from "@/app/app/message/messageComponents/interfaces";
import { MessageTextRenderer } from "@/app/app/message/messageComponents/renderers/MessageTextRenderer";
import { ImageToolRenderer } from "@/app/app/message/messageComponents/renderers/ImageToolRenderer";
import { PythonToolRenderer } from "@/app/app/message/messageComponents/timeline/renderers/code/PythonToolRenderer";
import { CodingAgentRenderer } from "@/app/app/message/messageComponents/timeline/renderers/code/CodingAgentRenderer";
import { ReasoningRenderer } from "@/app/app/message/messageComponents/timeline/renderers/reasoning/ReasoningRenderer";
import CustomToolRenderer from "@/app/app/message/messageComponents/renderers/CustomToolRenderer";
import { FileReaderToolRenderer } from "@/app/app/message/messageComponents/timeline/renderers/filereader/FileReaderToolRenderer";
import { FetchToolRenderer } from "@/app/app/message/messageComponents/timeline/renderers/fetch/FetchToolRenderer";
import { MemoryToolRenderer } from "@/app/app/message/messageComponents/timeline/renderers/memory/MemoryToolRenderer";
import { DeepResearchPlanRenderer } from "@/app/app/message/messageComponents/timeline/renderers/deepresearch/DeepResearchPlanRenderer";
import { ResearchAgentRenderer } from "@/app/app/message/messageComponents/timeline/renderers/deepresearch/ResearchAgentRenderer";
import { WebSearchToolRenderer } from "@/app/app/message/messageComponents/timeline/renderers/search/WebSearchToolRenderer";
import { InternalSearchToolRenderer } from "@/app/app/message/messageComponents/timeline/renderers/search/InternalSearchToolRenderer";

export function findRenderer({
  items,
}: {
  items: ResponseItem[];
}): MessageRenderer<ResponseItem, FullChatState> | null {
  const first = items[0]?.content;
  if (!first) return null;
  if (first.kind === "text")
    return first.purpose === "plan"
      ? DeepResearchPlanRenderer
      : first.purpose === "report"
        ? ResearchAgentRenderer
        : MessageTextRenderer;
  if (first.kind === "reasoning") return ReasoningRenderer;
  if (first.status === "error" && first.metadata === null)
    return CustomToolRenderer;
  switch (first.name) {
    case "coding_agent":
    case "bash":
      return CodingAgentRenderer;
    case "research_agent":
      return ResearchAgentRenderer;
    case "web_search":
      return WebSearchToolRenderer;
    case "internal_search":
      return InternalSearchToolRenderer;
    case "generate_image":
      return ImageToolRenderer;
    case "run_python":
    case "python":
      return PythonToolRenderer;
    case "read_file":
      return FileReaderToolRenderer;
    case "open_url":
      return FetchToolRenderer;
    case "add_memory":
      return MemoryToolRenderer;
    default:
      return CustomToolRenderer;
  }
}

interface RendererComponentProps {
  items: ResponseItem[];
  chatState: FullChatState;
  messageNodeId?: number;
  hasTimelineThinking?: boolean;
  onComplete: () => void;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  children: (result: RendererOutput) => JSX.Element;
}

export const RendererComponent = memo(function RendererComponent({
  items,
  chatState,
  messageNodeId,
  hasTimelineThinking,
  onComplete,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}: RendererComponentProps) {
  const Renderer = findRenderer({ items });
  if (!Renderer)
    return children([{ icon: null, status: null, content: <></> }]);
  return (
    <Renderer
      items={items}
      state={chatState}
      messageNodeId={messageNodeId}
      hasTimelineThinking={hasTimelineThinking}
      onComplete={onComplete}
      animate={animate}
      renderType={RenderType.FULL}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
    >
      {children}
    </Renderer>
  );
});
