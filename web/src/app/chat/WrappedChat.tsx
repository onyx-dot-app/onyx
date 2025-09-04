"use client";

import { useChatContext } from "@/components/context/ChatContext";
import { ChatPage } from "./components/ChatPage";
import { useCallback, useState } from "react";

export default function ChatLayout({
  firstMessage,
  defaultSidebarOff,
}: {
  firstMessage?: string;
  // This is required for the chrome extension side panel
  // we don't want to show the sidebar by default when the user opens the side panel
  defaultSidebarOff?: boolean;
}) {
  const { sidebarInitiallyVisible } = useChatContext();

  const [sidebarVisible, setSidebarVisible] = useState(
    (sidebarInitiallyVisible && !defaultSidebarOff) ?? false
  );

  const toggle = useCallback((value?: boolean) => {
    setSidebarVisible((sidebarVisiblePrevValue) =>
      value !== undefined ? value : !sidebarVisiblePrevValue
    );
  }, []);

  return (
    <>
      <div className="overscroll-y-contain overflow-y-scroll overscroll-contain left-0 top-0 w-full h-svh">
        <ChatPage
          toggle={toggle}
          sidebarVisible={sidebarVisible}
          firstMessage={firstMessage}
        />
      </div>
    </>
  );
}
