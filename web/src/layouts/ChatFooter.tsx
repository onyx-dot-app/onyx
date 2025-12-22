"use client";

import Text from "@/refresh-components/texts/Text";
import { CombinedSettings } from "@/app/admin/settings/interfaces";

export interface ChatFooterProps {
  settings: CombinedSettings | null;
}

export default function ChatFooter({ settings }: ChatFooterProps) {
  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content;

  return (
    <footer className="w-full flex flex-row justify-center items-center gap-2 h-16">
      {customFooterContent && (
        <Text text03 secondaryBody>
          {customFooterContent}
        </Text>
      )}
    </footer>
  );
}
