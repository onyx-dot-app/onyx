"use client";
import { useChatContext } from "@/components/context/ChatContext";

import FunctionalWrapper from "../../../components/chat/FunctionalWrapper";
import SearchPage from "./SearchPage";
import { redirect } from "next/navigation";
import { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";

export default function WrappedSearch({
  defaultSidebarOff,
  isTransitioningFromChat,
}: {
  // This is required for the chrome extension side panel
  // we don't want to show the sidebar by default when the user opens the side panel
  defaultSidebarOff?: boolean;
  isTransitioningFromChat?: boolean;
}) {
  const combinedSettings = useContext(SettingsContext);
  const isSearchPageDisabled = combinedSettings?.settings.search_page_disabled;
  if (isSearchPageDisabled) {
    redirect("/chat");
  }
  return (
    // <FunctionalWrapper
    // content={(sidebarVisible, toggle) => (
    <SearchPage
      toggle={() => {}}
      sidebarVisible={false}
      firstMessage={undefined}
      isTransitioningFromChat={isTransitioningFromChat}
    />
    // )}
    // />
  );
}
