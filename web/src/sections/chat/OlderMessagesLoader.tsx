"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Section } from "@opal/layouts";
import { ChatMessageLoader } from "@opal/loaders";
import { cn } from "@opal/utils";
import { useOptionalChatScroll } from "@/lib/chatScroll/components";
import {
  useChatSessionStore,
  useIsLoadingOlderMessages,
} from "@/app/app/stores/useChatSessionStore";
import { loadOlderChatMessages } from "@/lib/chat/pagedSession";

export interface OlderMessagesLoaderProps {
  className?: string;
}

/**
 * A message skeleton above the loaded messages of a paged chat. When it
 * comes within the rows' overscan margin of the viewport, it loads the next page of
 * older messages, once the user has scrolled. The scroll view keeps the
 * loaded messages still when a page is added above.
 */
export default function OlderMessagesLoader({
  className,
}: OlderMessagesLoaderProps) {
  const t = useTranslations("chat.app");
  const scroll = useOptionalChatScroll();
  const observeNearViewport = scroll?.observeNearViewport;
  // Opening a chat restores its position from loaded rows; a page loads
  // only once the user scrolls.
  const scrolledByUser = scroll?.scrolledByUser ?? true;
  const loaderRef = useRef<HTMLDivElement>(null);
  const isLoading = useIsLoadingOlderMessages();

  // Observed again after each page: a loader still in range loads the next.
  useEffect(() => {
    const loader = loaderRef.current;
    if (!observeNearViewport || !loader || isLoading || !scrolledByUser) return;

    return observeNearViewport(loader, (near) => {
      const sessionId = useChatSessionStore.getState().currentSessionId;
      if (near && sessionId) {
        void loadOlderChatMessages(sessionId);
      }
    });
  }, [observeNearViewport, isLoading, scrolledByUser]);

  return (
    <div
      ref={loaderRef}
      role="status"
      aria-label={t("olderMessagesLoader.ariaLabel")}
      className={cn("w-full self-center", className)}
    >
      <Section gap={12} height="fit">
        <ChatMessageLoader orientation="end" />
        <ChatMessageLoader orientation="start" />
      </Section>
    </div>
  );
}
