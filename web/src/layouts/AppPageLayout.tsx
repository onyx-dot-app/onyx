"use client";

import ChatHeader from "./ChatHeader";
import ChatFooter from "./ChatFooter";
import useChatSessions from "@/hooks/useChatSessions";
import { useSettingsContext } from "@/components/settings/SettingsProvider";

export interface AppPageLayoutProps {
  children?: React.ReactNode;
}

// AppPageLayout wraps chat pages with the shared header/footer white-labelling chrome.
// The header provides "Share Chat" and kebab-menu functionality for shareable chat pages.
//
// Since this is such a ubiquitous component, it's been moved to its own `layouts` directory.
export default function AppPageLayout({ children }: AppPageLayoutProps) {
  const { currentChatSession } = useChatSessions();
  const settings = useSettingsContext();

  return (
    <div className="flex flex-col h-full w-full">
      <ChatHeader />
      <div className="flex-1 overflow-auto h-full w-full">{children}</div>
      <ChatFooter />
    </div>
  );
}
