"use client";

import { ChatPage } from "../chat/ChatPage";
import FunctionalWrapper from "../chat/shared_chat_search/FunctionalWrapper";
import NRFPage from "./NRFPage";

export default function WrappedNRF({
  initiallyToggled,
}: {
  initiallyToggled: boolean;
}) {
  return (
    <FunctionalWrapper
      initiallyToggled={initiallyToggled}
      content={(toggledSidebar, toggle) => (
        <NRFPage
          toggledSidebar={toggledSidebar}
          toggle={toggle}
          documentSidebarInitialWidth={400}
        />
      )}
    />
  );
}
