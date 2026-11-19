"use client";

import React, { ForwardedRef } from "react";
import { cn } from "@opal/utils";
import { CHAT_GUTTER } from "@/lib/chat/layout";
import {
  ChatScrollView,
  type ChatScrollViewHandle,
} from "@/lib/chatScroll/components";

export type ChatScrollContainerHandle = ChatScrollViewHandle;

export interface ChatScrollContainerProps {
  children: React.ReactNode;
  /** The chat shown. A change opens it at its saved position. */
  sessionId?: string;
  /** Restore each chat's position when it opens again. */
  rememberPosition?: boolean;
  /** DOM id of the latest user message, the anchor of a new turn. */
  anchorId?: string;
  /** Changes when a new turn appears (the last row's id). */
  turnKey?: string;
  /** Follow new content while at the end. */
  autoScroll?: boolean;
  onScrollButtonVisibilityChange?: (visible: boolean) => void;
  /** Hide the scrollbar (scroll still works, just invisible) */
  hideScrollbar?: boolean;
  /** Full-width mode: edge-to-edge scroll container instead of the centered
   *  reading layout (drops the reserved scrollbar gutter). */
  fullWidth?: boolean;
}

// Fade content opacity over 1rem at the top and bottom edges.
const CONTENT_MASK =
  "linear-gradient(to bottom, transparent 0%, black 1rem, black calc(100% - 1rem), transparent 100%)";

/** The chat page's scroll view: `ChatScrollView` in the chat layout. */
const ChatScrollContainer = React.memo(
  React.forwardRef(function ChatScrollContainer(
    {
      children,
      sessionId,
      rememberPosition = true,
      anchorId,
      turnKey,
      autoScroll = true,
      onScrollButtonVisibilityChange,
      hideScrollbar = false,
      fullWidth = false,
    }: ChatScrollContainerProps,
    ref: ForwardedRef<ChatScrollContainerHandle>
  ) {
    return (
      <div className="flex flex-col flex-1 min-h-0 w-full relative overflow-hidden mb-1">
        <ChatScrollView
          ref={ref}
          viewKey={sessionId}
          rememberPosition={rememberPosition}
          autoScroll={autoScroll}
          turnKey={turnKey}
          anchorId={anchorId}
          onScrollButtonVisibilityChange={onScrollButtonVisibilityChange}
          data-testid="chat-scroll-container"
          className={cn(
            "flex flex-col flex-1 min-h-0 overflow-y-auto overflow-x-hidden",
            hideScrollbar ? "no-scrollbar" : "default-scrollbar",
            // Full-width (always the case below md) drops the reserved
            // gutters so content sits flush with the chat edge; centered
            // mode keeps both-edges to avoid shift.
            !fullWidth && "md:[scrollbar-gutter:stable_both-edges]"
          )}
          style={{ maskImage: CONTENT_MASK, WebkitMaskImage: CONTENT_MASK }}
          contentClassName={cn(
            "w-full flex-1 flex flex-col items-center",
            CHAT_GUTTER
          )}
        >
          {/* A chat's rows never carry over to the next chat. */}
          <React.Fragment key={sessionId}>{children}</React.Fragment>
        </ChatScrollView>
      </div>
    );
  })
);

ChatScrollContainer.displayName = "ChatScrollContainer";

export default ChatScrollContainer;
