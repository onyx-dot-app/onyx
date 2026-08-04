// Render-prop renderer contract, ported from web `messageComponents/interfaces.ts` (docs 9b-timeline/03
// §4). A renderer is headless: it computes a `RendererResult[]` and hands it to `children(results)`; the
// parent owns the tree. Mobile drops web's `isHover` and the dead `expandedText`, and narrows
// `FullChatState` to the fields mobile renderers read.
import type { ComponentType, ReactElement } from "react";

import { MinimalAgent } from "@/chat/agents";
import { CitationMap, SearchDoc } from "@/chat/contracts/documents";
import { Packet, StopReason } from "@/chat/streamingModels";
import type { IconFunctionComponent } from "@/icons/types";

export enum RenderType {
  HIGHLIGHT = "highlight",
  FULL = "full",
  COMPACT = "compact",
  INLINE = "inline",
}

// "timeline": parent wraps the result in a StepContainer. "content": renderer carries its own layout.
export type TimelineLayout = "timeline" | "content";

// Surface behind a timeline step's body; "error" for auth/tool failures.
export type TimelineSurfaceBackground = "tint" | "transparent" | "error";

export interface RendererResult {
  icon: IconFunctionComponent | null;
  status: string | ReactElement | null;
  content: ReactElement;
  supportsCollapsible?: boolean;
  // Collapsible even when it's the only step in the timeline.
  alwaysCollapsible?: boolean;
  timelineLayout?: TimelineLayout;
  // Long-form content (reasoning, deep research, memory) drops right padding.
  noPaddingRight?: boolean;
  surfaceBackground?: TimelineSurfaceBackground;
}

// Single-step renderers return a 1-element array.
export type RendererOutput = RendererResult[];

// Mobile's subset of web's FullChatState — the context a renderer may read.
export interface FullChatState {
  agent: MinimalAgent | null;
  citations?: CitationMap;
  documentMap?: Map<string, SearchDoc>;
  // Opens a cited source (9a); used by later source-row renderers.
  openSource?: (doc: SearchDoc) => void;
  // Opens the long-form reader the message row owns, identified by the step's packet-group key.
  // Two reasons it takes a key rather than the text: the timeline auto-collapses when the answer
  // starts, so a reader owned inside the step would be unmounted mid-read; and a snapshot string
  // would freeze while the step keeps streaming, so the row re-derives the text on every flush.
  openFullText?: (groupKey: string) => void;
}

export type MessageRenderer<
  T extends Packet,
  S extends Partial<FullChatState>,
> = ComponentType<{
  packets: T[];
  state: S;
  messageNodeId?: number;
  // True when timeline/thinking UI is already shown above this block.
  hasTimelineThinking?: boolean;
  onComplete: () => void;
  renderType: RenderType;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  // Last step in the timeline (connector-line decisions).
  isLastStep?: boolean;
  children: (result: RendererOutput) => ReactElement;
}>;

// The dispatch surface. `findRenderer` returns this widened form; concrete renderers narrow their packet
// type internally instead of exposing `any` at the boundary.
export type DispatchRenderer = MessageRenderer<Packet, FullChatState>;

// RendererResult plus per-step expand/collapse state (produced by TimelineRendererComponent in 9b.5).
// Present now so the contract is complete; unused until the timeline UI lands.
export interface TimelineRendererResult extends RendererResult {
  isExpanded: boolean;
  onToggle: () => void;
  renderType: RenderType;
  isLastStep: boolean;
  timelineLayout: TimelineLayout;
}
