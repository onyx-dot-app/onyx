"use client";

import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { FOLDED_SIZE } from "@/refresh-components/Logo";
import { useAppFocus } from "@/lib/hooks";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgShare from "@/icons/share";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import { useState } from "react";
import ShareChatSessionModal from "@/app/chat/components/modal/ShareChatSessionModal";

export default function AppLayout({
  className,
  children,
  ...rest
}: React.HtmlHTMLAttributes<HTMLDivElement>) {
  const settings = useSettingsContext();
  const customHeaderContent =
    settings.enterpriseSettings?.custom_header_content;
  const customFooterContent =
    settings.enterpriseSettings?.custom_lower_disclaimer_content;
  const customLogo = settings.enterpriseSettings?.use_custom_logo;

  const appFocus = useAppFocus();
  const { chatSessions } = useChatContext();
  const [showShareModal, setShowShareModal] = useState(false);

  const currentChatSession =
    typeof appFocus === "object" && appFocus.type === "chat"
      ? chatSessions.find((session) => session.id === appFocus.id)
      : undefined;

  return (
    <>
      {showShareModal && currentChatSession && (
        <ShareChatSessionModal
          chatSession={currentChatSession}
          onClose={() => setShowShareModal(false)}
        />
      )}

      <div className="flex flex-col h-full w-full">
        {/* Header */}
        <header className="w-full flex flex-row justify-center items-center py-3 px-4">
          <div className="flex-1" />
          <div className="flex-1 flex flex-col items-center">
            <Text text03 className={cn(!customHeaderContent && "invisible")}>
              {customHeaderContent}
            </Text>
          </div>
          <div className="flex-1 flex flex-row items-center justify-end px-1">
            <IconButton
              icon={SvgShare}
              transient={showShareModal}
              tertiary
              onClick={() => setShowShareModal(true)}
              className={cn(!currentChatSession && "invisible")}
            />
          </div>
        </header>

        <div className={cn("flex-1 overflow-auto", className)} {...rest}>
          {children}
        </div>

        {(customLogo || customFooterContent) && (
          <footer className="w-full flex flex-row justify-center items-center gap-2 py-3">
            {customLogo && (
              <img
                src="/api/enterprise-settings/logo"
                alt="Logo"
                style={{
                  objectFit: "contain",
                  height: FOLDED_SIZE,
                  width: FOLDED_SIZE,
                }}
                className="flex-shrink-0"
              />
            )}
            {customFooterContent && (
              <Text text03 secondaryBody>
                {customFooterContent}
              </Text>
            )}
          </footer>
        )}
      </div>
    </>
  );
}
