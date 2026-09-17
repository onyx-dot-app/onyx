import {
  ChatItem,
  Placement,
  ResponseItem,
  RunStatus,
} from "@/chat/streamingModels";
import { makeItem as responseItem } from "@/chat/__tests__/fixtures";
import { TransformedStep, TurnGroup } from "@/chat/timeline/transformers";

export function makeItem(
  name: string,
  placement: Partial<Placement> = {},
  options: {
    text?: string;
    status?: RunStatus;
    purpose?: "answer" | "plan";
    toolName?: string;
  } = {},
): ResponseItem {
  const status = options.status ?? "running";
  const content: ChatItem =
    name === "reasoning"
      ? { kind: "reasoning", text: options.text ?? "", status }
      : name === "text"
        ? {
            kind: "text",
            text: options.text ?? "",
            purpose: options.purpose ?? "answer",
            status,
            documents: [],
            citations: [],
          }
        : {
            kind: "tool",
            name: options.toolName ?? name,
            arguments: {},
            status,
            output: "",
            metadata: null,
          };
  return responseItem(
    content,
    placement,
    `${placement.turn_index ?? 0}-${placement.tab_index ?? 0}-${name}`,
  );
}
export function makeStep(
  turnIndex: number,
  tabIndex: number,
  items: ResponseItem[],
): TransformedStep {
  return { key: `${turnIndex}-${tabIndex}`, turnIndex, tabIndex, items };
}
export function makeTurn(
  turnIndex: number,
  steps: TransformedStep[],
): TurnGroup {
  return { turnIndex, steps, isParallel: steps.length > 1 };
}
