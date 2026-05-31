// interfaces.ts — the renderer contract for the agent-message timeline.
//
// Ported from web:
//   web/src/app/app/message/messageComponents/interfaces.ts
// AMENDMENT: RendererResult.icon is a TimelineIconName (string), not a React
// component, so the pure state/timeline layer stays leaf. The components layer
// maps the name to an Svg* via `timeline/toolIcon`.

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

/** How a per-tool renderer should draw its content. */
export enum RenderType {
  HIGHLIGHT = "highlight",
  FULL = "full",
  COMPACT = "compact",
  INLINE = "inline",
}

/** "timeline" => wrap result in StepContainer chrome; "content" => renderer drew its own. */
export type TimelineLayout = "timeline" | "content";

export type TimelineSurfaceBackground = "tint" | "transparent" | "error";

/** Shared context threaded into every renderer. */
export interface FullChatState {
  agent: MinimalAgent;
  docs?: OnyxDocument[] | null;
  citations?: CitationMap;
  /** Open a document (mobile: a detail bottom-sheet or external link). */
  setPresentingDocument?: (doc: MinimalOnyxDocument) => void;
  overriddenModel?: string;
  researchType?: string | null;
}

/** One unit of renderer output that the timeline shell composes. */
export interface RendererResult {
  /** Step icon name (mapped to an Svg* in the components layer), or null. */
  icon: TimelineIconName | null;
  /** Header/status label (string, or a node for richer headers). */
  status: string | ReactNode | null;
  /** Body content. */
  content: ReactNode;
  /** Override look in the expanded view (e.g. ReasoningRenderer). */
  expandedText?: ReactNode;
  /** Show the collapse button only when true. */
  supportsCollapsible?: boolean;
  /** Stay collapsible even in single-step timelines (e.g. Python). */
  alwaysCollapsible?: boolean;
  /** "content" => render as-is (no StepContainer); "timeline" => wrap. */
  timelineLayout?: TimelineLayout;
  /** Remove right padding for long-form content. */
  noPaddingRight?: boolean;
  /** Surface background variant. */
  surfaceBackground?: TimelineSurfaceBackground;
}

export type RendererOutput = RendererResult[];

/** Props every per-tool renderer receives. The only output channel is `children(results)`. */
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
