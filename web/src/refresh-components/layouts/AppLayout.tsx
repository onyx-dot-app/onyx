"use client";

import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { cn } from "@/lib/utils";

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

  return (
    <div className="flex flex-col h-screen dbg-red">
      {/* Header */}
      {customHeaderContent && (
        <header
          className="w-full dbg-red"
          dangerouslySetInnerHTML={{ __html: customHeaderContent }}
        />
      )}

      {/* Main Content */}
      <main className={cn("flex-1 overflow-auto dbg-red", className)} {...rest}>
        {children}
      </main>

      {/* Footer */}
      {customFooterContent && (
        <div
          className="w-full dbg-red"
          // dangerouslySetInnerHTML={{ __html: customFooterContent }}
        >
          {customFooterContent}
        </div>
      )}
    </div>
  );
}
