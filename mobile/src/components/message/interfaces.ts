// Mirrors web interfaces.ts. Deviation: RendererResult.icon is a TimelineIconName
// (string), not a React component, so the pure state/timeline layer stays leaf.
// The components layer maps the name to an Svg* via `timeline/toolIcon`.

import type { ReactNode } from "react";
import type {
  MinimalAgent,
  OnyxDocument,
  MinimalOnyxDocument,
  CitationMap,
  StopReason,
  Packet,
} from "@/lib/types";
import type { TimelineIconName } from "@/state/timeline/toolDisplayHelpers";

export enum RenderType {
  HIGHLIGHT = "highlight",
  FULL = "full",
  COMPACT = "compact",
  INLINE = "inline",
}

// "timeline" => wrap result in StepContainer chrome; "content" => renderer drew its own.
export type TimelineLayout = "timeline" | "content";

export type TimelineSurfaceBackground = "tint" | "transparent" | "error";

export interface FullChatState {
  agent: MinimalAgent;
  docs?: OnyxDocument[] | null;
  citations?: CitationMap;
  // Mobile: opens a detail bottom-sheet or external link.
  setPresentingDocument?: (doc: MinimalOnyxDocument) => void;
  overriddenModel?: string;
  researchType?: string | null;
}

export interface RendererResult {
  icon: TimelineIconName | null;
  status: string | ReactNode | null;
  content: ReactNode;
  supportsCollapsible?: boolean;
  // Stay collapsible even in single-step timelines (e.g. Python).
  alwaysCollapsible?: boolean;
  timelineLayout?: TimelineLayout;
  noPaddingRight?: boolean;
  surfaceBackground?: TimelineSurfaceBackground;
}

export type RendererOutput = RendererResult[];

// The only output channel is `children(results)`.
export interface MessageRendererProps<T extends Packet, S = FullChatState> {
  packets: T[];
  state: S;
  messageNodeId?: number;
  hasTimelineThinking?: boolean;
  onComplete: () => void;
  renderType: RenderType;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  isLastStep?: boolean;
  children: (result: RendererOutput) => ReactNode;
}

export type MessageRenderer<T extends Packet, S = FullChatState> = (
  props: MessageRendererProps<T, S>
) => ReactNode;
