import type { ToolCallState } from "@/app/craft/types/displayTypes";

export type ToolCardDensity = "compact" | "comfortable";

export interface ToolCardBodyProps {
  toolCall: ToolCallState;
}

export interface ToolCardCommonProps {
  toolCall: ToolCallState;
  density?: ToolCardDensity;
  defaultOpen?: boolean;
}
