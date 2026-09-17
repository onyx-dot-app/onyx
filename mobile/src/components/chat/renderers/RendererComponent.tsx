// Picks the renderer for a group's items, invokes it at FULL, and forwards its `RendererResult[]` to
// `children` (web `renderMessageComponent`). Memoized on packet identity so parent streaming re-renders
// don't churn the answer subtree unless these items grew.
import { memo } from "react";
import type { ComponentProps, ReactElement } from "react";

import { ResponseItem, StopReason } from "@/chat/streamingModels";

import { findRenderer } from "./findRenderer";
import { RenderType } from "./timelineContract";
import type {
  DispatchRenderer,
  FullChatState,
  RendererOutput,
} from "./timelineContract";

// Renders the dispatched renderer via a prop, not a call-result directly in JSX — the latter trips
// react-hooks/static-components (same shape `Icon` uses for `as`). Identical to web's `<RendererFn/>`.
function DispatchedRenderer({
  renderer: Renderer,
  ...rendererProps
}: { renderer: DispatchRenderer } & ComponentProps<DispatchRenderer>) {
  return <Renderer {...rendererProps} />;
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
  children: (result: RendererOutput) => ReactElement;
}

function RendererComponentImpl({
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
  // Mobile has no image renderer yet.
  const RendererFn = findRenderer(items);

  if (!RendererFn) {
    return children([{ icon: null, status: null, content: <></> }]);
  }

  return (
    <DispatchedRenderer
      renderer={RendererFn}
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
    </DispatchedRenderer>
  );
}

// Skips `onComplete`/`children` (unstable identities) and `chatState` identity; `agent.id` covers the
// only chatState change that affects output.
function areRendererPropsEqual(
  prev: RendererComponentProps,
  next: RendererComponentProps,
): boolean {
  return (
    prev.items === next.items &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.animate === next.animate &&
    prev.chatState.agent?.id === next.chatState.agent?.id &&
    prev.messageNodeId === next.messageNodeId
  );
}

export const RendererComponent = memo(
  RendererComponentImpl,
  areRendererPropsEqual,
);
