"use client";

import { useState } from "react";
import { ChatPage } from "./ChatPage";
import FunctionalWrapper from "./shared_chat_search/FunctionalWrapper";

export default function WrappedChat({
  defaultPersonaId,
  initiallyToggled,
}: {
  defaultPersonaId?: number;
  initiallyToggled: boolean;
}) {
  return (
    <FunctionalWrapper
      initiallyToggled={initiallyToggled}
      content={(toggledSidebar, toggle) => (
        <ChatPage
          toggle={toggle}
          defaultSelectedPersonaId={defaultPersonaId}
          toggledSidebar={toggledSidebar}
        />
      )}
    />
  );
}
