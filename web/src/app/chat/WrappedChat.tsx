"use client";
import { ChatPage } from "./ChatPage";
import FunctionalWrapper from "./shared_chat_search/FunctionalWrapper";

export default function WrappedChat({
  defaultAssistantId,
  initiallyToggled,
}: {
  defaultAssistantId?: number;
  initiallyToggled: boolean;
}) {
  return (
    <FunctionalWrapper
      initiallyToggled={initiallyToggled}
      content={(toggledSidebar, toggle) => (
        <ChatPage
          toggle={toggle}
          defaultSelectedAssistantId={defaultAssistantId}
          toggledSidebar={toggledSidebar}
        />
      )}
    />
  );
}
