// Picks the renderer for a group's packets, invokes it at FULL, and forwards its `RendererResult[]` to
// `children` (web `renderMessageComponent`). Memoized on packet identity so parent streaming re-renders
// don't churn the answer subtree unless these packets grew.
import { memo } from "react";
import type { ComponentProps, ReactElement } from "react";

import { Packet, StopReason } from "@/chat/streamingModels";

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
  packets: Packet[];
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
  packets,
  chatState,
  messageNodeId,
  hasTimelineThinking,
  onComplete,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}: RendererComponentProps) {
  // 9e: web splits mixed chat+image groups via a MixedContentHandler. No image renderer yet, so mixed
  // groups fall through to the chat renderer (image dropped) until then.
  const RendererFn = findRenderer(packets);

  if (!RendererFn) {
    return children([{ icon: null, status: null, content: <></> }]);
  }

  return (
    <DispatchedRenderer
      renderer={RendererFn}
      packets={packets}
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
    prev.packets === next.packets &&
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
