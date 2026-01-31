/**
 * App Page Layout Components
 *
 * Provides the root layout and footer for app pages.
 * AppRoot renders AppHeader and Footer by default (both can be disabled via props).
 *
 * @example
 * ```tsx
 * import * as AppLayouts from "@/layouts/app-layouts";
 *
 * export default function ChatPage() {
 *   return (
 *     <AppLayouts.Root>
 *       <ChatInterface />
 *     </AppLayouts.Root>
 *   );
 * }
 * ```
 */

"use client";

import { cn, ensureHrefProtocol } from "@/lib/utils";
import type { Components } from "react-markdown";
import Text from "@/refresh-components/texts/Text";
import AppHeader from "@/app/app/components/AppHeader";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { useSettingsContext } from "@/providers/SettingsProvider";

const footerMarkdownComponents = {
  p: ({ children }) => (
    //dont remove the !my-0 class, it's important for the markdown to render without any alignment issues
    <Text as="p" text03 secondaryAction className="!my-0 text-center">
      {children}
    </Text>
  ),
  a: ({ node, href, className, children, ...rest }) => {
    const fullHref = ensureHrefProtocol(href);
    return (
      <a
        href={fullHref}
        target="_blank"
        rel="noopener noreferrer"
        {...rest}
        className={cn(className, "underline underline-offset-2")}
      >
        <Text text03 secondaryAction>
          {children}
        </Text>
      </a>
    );
  },
} satisfies Partial<Components>;

function Footer() {
  const settings = useSettingsContext();

  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${
      settings?.webVersion || "dev"
    }](https://www.onyx.app/) - Open Source AI Platform`;

  return (
    <footer className="relative w-full flex flex-row justify-center items-center gap-2 pb-2 mt-auto">
      <MinimalMarkdown
        content={customFooterContent}
        className={cn("max-w-full text-center")}
        components={footerMarkdownComponents}
      />
    </footer>
  );
}

/**
 * App Root Component
 *
 * Wraps app pages with header (AppHeader) and footer chrome.
 *
 * Layout Structure:
 * ```
 * ┌──────────────────────────────────┐
 * │ AppHeader                        │
 * ├──────────────────────────────────┤
 * │                                  │
 * │ Content Area (children)          │
 * │                                  │
 * ├──────────────────────────────────┤
 * │ Footer (custom disclaimer)       │
 * └──────────────────────────────────┘
 * ```
 *
 * @example
 * ```tsx
 * <AppLayouts.Root>
 *   <ChatInterface />
 * </AppLayouts.Root>
 * ```
 */
export interface AppRootProps {
  /**
   * @deprecated This prop should rarely be used. Prefer letting the Header render.
   */
  disableHeader?: boolean;
  /**
   * @deprecated This prop should rarely be used. Prefer letting the Footer render.
   */
  disableFooter?: boolean;
  children?: React.ReactNode;
}

function AppRoot({ children, disableHeader, disableFooter }: AppRootProps) {
  return (
    /* NOTE: Some elements, markdown tables in particular, refer to this `@container` in order to
      breakout of their immediate containers using cqw units.
    */
    <div className="@container flex flex-col h-full w-full relative overflow-hidden">
      {!disableHeader && <AppHeader />}
      <div className="flex-1 overflow-auto h-full w-full">{children}</div>
      {!disableFooter && <Footer />}
    </div>
  );
}

export { AppRoot as Root, Footer };
