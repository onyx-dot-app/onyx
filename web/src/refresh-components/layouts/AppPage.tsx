"use client";

import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { FOLDED_SIZE } from "@/refresh-components/Logo";
import Button from "@/refresh-components/buttons/Button";
import SvgShare from "@/icons/share";
import { useState } from "react";
import ShareChatSessionModal from "@/app/chat/components/modal/ShareChatSessionModal";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { ChatSession } from "@/app/chat/interfaces";

export interface AppPageProps extends React.HtmlHTMLAttributes<HTMLDivElement> {
  settings: CombinedSettings | null;
  chatSession: ChatSession | null;
}

export default function AppPage({
  settings,
  chatSession,

  className,
  children,
  ...rest
}: AppPageProps) {
  const customHeaderContent =
    settings?.enterpriseSettings?.custom_header_content;
  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content;
  const customLogo = settings?.enterpriseSettings?.use_custom_logo;
  const [showShareModal, setShowShareModal] = useState(false);

  return (
    <>
      {chatSession && showShareModal && (
        <ShareChatSessionModal
          chatSession={chatSession}
          onClose={() => setShowShareModal(false)}
        />
      )}

      <div className="flex flex-col h-full w-full">
        {/* Header */}
        {(customHeaderContent || chatSession) && (
          <header className="w-full flex flex-row justify-center items-center py-3 px-4">
            <div className="flex-1" />
            <div className="flex-1 flex flex-col items-center">
              <Text text03>{customHeaderContent}</Text>
            </div>
            <div className="flex-1 flex flex-row items-center justify-end px-1">
              <Button
                rightIcon={SvgShare}
                transient={showShareModal}
                tertiary
                onClick={() => setShowShareModal(true)}
              >
                Share Chat
              </Button>
            </div>
          </header>
        )}

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
