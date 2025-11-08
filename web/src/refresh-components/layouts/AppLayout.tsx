"use client";

import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { FOLDED_SIZE } from "@/refresh-components/Logo";

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

  return (
    <div className="flex flex-col h-full w-full">
      {/* Header */}
      {customHeaderContent && (
        <header className="w-full flex flex-col items-center py-3">
          <Text text03>{customHeaderContent}</Text>
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
