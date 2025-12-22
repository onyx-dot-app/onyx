"use client";

import { ChatSession } from "@/app/chat/interfaces";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import ChatHeader from "./ChatHeader";

export interface AppPageLayoutProps
  extends React.HtmlHTMLAttributes<HTMLDivElement> {
  settings: CombinedSettings | null;
  chatSession: ChatSession | null;
}

// AppPageLayout wraps chat pages with the shared header/footer white-labelling chrome.
// The header provides "Share Chat" and kebab-menu functionality for shareable chat pages.
//
// Since this is such a ubiquitous component, it's been moved to its own `layouts` directory.
export default function AppPageLayout({
  settings,
  chatSession,
  className,
  ...rest
}: AppPageLayoutProps) {
  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content;

  return (
    <div className="flex flex-col h-full w-full">
      <ChatHeader settings={settings} chatSession={chatSession} />

      <div className={cn("flex-1 overflow-auto", className)} {...rest} />

      {customFooterContent && (
        <footer className="w-full flex flex-row justify-center items-center gap-2 py-3">
          <Text text03 secondaryBody>
            {customFooterContent}
          </Text>
        </footer>
      )}
    </div>
  );
}
