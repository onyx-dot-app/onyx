"use client";
import { ChatPage } from "./ChatPage";
import FunctionalWrapper from "./shared_chat_search/FunctionalWrapper";
import { Footer } from "@/components/Footer";

export default function WrappedChat({
  defaultAssistantId,
  initiallyToggled,
  footerHtml,
}: {
  defaultAssistantId?: number;
  initiallyToggled: boolean;
  footerHtml?: any;
}) {
  return (
    <FunctionalWrapper
      initiallyToggled={initiallyToggled}
      content={(toggledSidebar, toggle) => (
        <ChatPage
          toggle={toggle}
          defaultSelectedAssistantId={defaultAssistantId}
          toggledSidebar={toggledSidebar}
          footerHtml={footerHtml}
        />
      )}
    />
  );
}
