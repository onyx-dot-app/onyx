"use client";
import { useChatContext } from "@/components/context/ChatContext";

import FunctionalWrapper from "../../components/chat/FunctionalWrapper";
import SearchPage from "./SearchPage";

export default function WrappedSearch({
  defaultSidebarOff,
}: {
  // This is required for the chrome extension side panel
  // we don't want to show the sidebar by default when the user opens the side panel
  defaultSidebarOff?: boolean;
}) {
  return (
    <FunctionalWrapper
      content={(sidebarVisible, toggle) => (
        <SearchPage
        //   toggle={toggle}
        //   sidebarVisible={sidebarVisible}
        //   firstMessage={firstMessage}
        />
      )}
    />
  );
}
