"use client";

import { useContext, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Section } from "@opal/layouts";
import { ChatMessageLoader } from "@opal/loaders";
import { cn } from "@opal/utils";
import { useOptionalScrollContainer } from "@/lib/chatScroll/components/ScrollContainerContext";
import {
  useChatSessionStore,
  useIsLoadingOlderMessages,
} from "@/app/app/stores/useChatSessionStore";
import { loadOlderChatMessages } from "@/lib/chat/pagedSession";
import { DynamicConversationsContext } from "@/providers/AppearancePreferencesProvider";

export interface OlderMessagesLoaderProps {
  className?: string;
}

/**
 * A message skeleton above the loaded messages of a paged chat. When it
 * comes within the rows' overscan margin of the viewport, it loads the next page of
 * older messages. With dynamic conversations off, it loads every older page,
 * one after another, without waiting for a scroll.
 *
 * It sets `overflow-anchor: none`, so the browser's scroll anchoring keeps
 * the loaded messages, not the skeleton, still when a page is added above.
 */
export default function OlderMessagesLoader({
  className,
}: OlderMessagesLoaderProps) {
  const t = useTranslations("chat.app");
  const observeNearViewport = useOptionalScrollContainer()?.observeNearViewport;
  const loaderRef = useRef<HTMLDivElement>(null);
  const isLoading = useIsLoadingOlderMessages();
  const dynamicConversations = useContext(DynamicConversationsContext);

  // Runs again after each page: a loader still in range loads the next.
  useEffect(() => {
    const loader = loaderRef.current;
    if (!loader || isLoading) return;
    const loadNextPage = () => {
      const sessionId = useChatSessionStore.getState().currentSessionId;
      if (sessionId) void loadOlderChatMessages(sessionId);
    };
    if (!dynamicConversations) {
      loadNextPage();
      return;
    }
    if (!observeNearViewport) return;

    return observeNearViewport(loader, (near) => {
      if (near) loadNextPage();
    });
  }, [observeNearViewport, isLoading, dynamicConversations]);

  return (
    <div
      ref={loaderRef}
      role="status"
      aria-label={t("olderMessagesLoader.ariaLabel")}
      className={cn("w-full self-center [overflow-anchor:none]", className)}
    >
      <Section gap={12} height="fit">
        <ChatMessageLoader orientation="end" />
        <ChatMessageLoader orientation="start" />
      </Section>
    </div>
  );
}
