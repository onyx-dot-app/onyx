"use client";

import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { FOLDED_SIZE } from "@/refresh-components/Logo";
import { useHeaderActionsValue } from "@/refresh-components/contexts/HeaderActionsContext";

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

  const { headerNode, reserveSpace } = useHeaderActionsValue();
  const shouldRenderHeader =
    !!customHeaderContent || reserveSpace || !!headerNode;

  return (
    <div className="flex flex-col h-full w-full">
      {/* Header */}
      {shouldRenderHeader && (
        <header className="w-full flex flex-row justify-center items-center py-3 px-4 h-16">
          <div className="flex-1" />
          <div className="flex-1 flex flex-col items-center justify-center">
            {customHeaderContent && <Text text03>{customHeaderContent}</Text>}
          </div>
          <div className="flex-1 flex flex-row items-center justify-end px-1">
            {headerNode}
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
  );
}
