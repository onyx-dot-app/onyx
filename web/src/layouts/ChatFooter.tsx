"use client";

import Text from "@/refresh-components/texts/Text";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { ChatSession } from "@/app/chat/interfaces";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { usePathname } from "next/navigation";

export interface ChatFooterProps {
  settings: CombinedSettings | null;
  chatSession: ChatSession | null;
}

export default function ChatFooter({ settings, chatSession }: ChatFooterProps) {
  const { currentProjectId } = useProjectsContext();
  const pathname = usePathname();
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

  // On the landing page (/chat with no chat session, no project), render an empty spacer
  // to balance the header and keep content centered
  const isLandingPage =
    pathname === "/chat" && !chatSession && !currentProjectId;
  if (isLandingPage) {
    return <div className="h-16" />;
  }

  return null;
}
