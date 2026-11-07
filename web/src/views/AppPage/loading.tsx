"use client";

import { useTranslations } from "next-intl";
import { ShadowDiv } from "@opal/components";
import { ChatMessageLoader } from "@opal/loaders";
import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import {
  CHAT_COLUMN_MAX_WIDTH,
  FULL_WIDTH_TRANSITION,
} from "@/sections/chat/constants";

/**
 * A chat while it loads: a conversation's shape in the chat column. Shown by
 * `AppPage` while a chat's messages first load, and by `AppChromeLoader`
 * from the click that opens a chat until `AppPage` mounts.
 */
export function ChatLoading() {
  const t = useTranslations("chat.app");
  return (
    <div className="h-full w-full px-2 sm:px-4 pt-6 pb-12">
      <Section justifyContent="start" gap={0}>
        {/* A conversation's shape in the chat column, from the
        top down like a real chat. More turns than fit, so it
        fills any height; the ones that overflow are clipped
        (not scrollable) and fade out at the bottom. The bottom
        keeps clear of the input bar. */}
        <ShadowDiv
          role="status"
          aria-label={t("firstOpenLoader.ariaLabel")}
          variant="mask"
          shadowDirection="bottom-only"
          containerClassName={cn(
            "w-full flex-1",
            CHAT_COLUMN_MAX_WIDTH,
            FULL_WIDTH_TRANSITION
          )}
          className="flex-1 min-h-0 overflow-y-hidden"
        >
          <Section gap={12} height="fit">
            {Array.from({ length: 8 }, (_, turn) => (
              <Section key={turn} gap={12} height="fit">
                <ChatMessageLoader orientation="end" />
                <ChatMessageLoader orientation="start" />
              </Section>
            ))}
          </Section>
        </ShadowDiv>
      </Section>
    </div>
  );
}
