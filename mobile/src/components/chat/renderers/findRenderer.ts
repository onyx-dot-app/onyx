import { ResponseItem } from "@/chat/streamingModels";
import { MessageTextRenderer } from "@/components/chat/renderers/MessageTextRenderer";
import { ReasoningRenderer } from "@/components/chat/renderers/ReasoningRenderer";
import { DispatchRenderer } from "@/components/chat/renderers/timelineContract";

export function findRenderer(items: ResponseItem[]): DispatchRenderer | null {
  const first = items[0]?.content;
  if (first?.kind === "text" && first.purpose === "answer")
    return MessageTextRenderer;
  if (first?.kind === "reasoning") return ReasoningRenderer;
  return null;
}
