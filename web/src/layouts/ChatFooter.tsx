"use client";

import Text from "@/refresh-components/texts/Text";
import useChatSessions from "@/hooks/useChatSessions";
import { useSettingsContext } from "@/components/settings/SettingsProvider";

export default function ChatFooter() {
  const { currentChatSession } = useChatSessions();
  const settings = useSettingsContext();

  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content;

  // When there's custom footer content, show it
  if (customFooterContent) {
    return (
      <footer className="w-full flex flex-row justify-center items-center gap-2 py-3">
        <Text text03 secondaryBody>
          {customFooterContent}
        </Text>
      </footer>
    );
  }

  // On the landing page (no chat session), render an empty spacer
  // to balance the header and keep content centered
  if (!currentChatSession) {
    return <div className="h-16" />;
  }

  return null;
}
