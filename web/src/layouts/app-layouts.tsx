/**
 * App Page Layout Components
 *
 * Layout components for chat/application pages including:
 * - AppRoot: Main layout wrapper with custom footer
 * - StickyHeader: Reusable sticky header wrapper
 *
 * @example
 * ```tsx
 * import AppLayouts, { StickyHeader } from "@/layouts/app-layouts";
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
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { useSettingsContext } from "@/components/settings/SettingsProvider";

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
        <Text as="span" text03 secondaryAction>
          {children}
        </Text>
      </a>
    );
  },
} satisfies Partial<Components>;

interface StickyHeaderProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Sticky Header Component
 *
 * Reusable sticky header wrapper for chat pages.
 * Provides consistent sticky positioning and base styling.
 */
function StickyHeader({ children, className }: StickyHeaderProps) {
  return (
    <header
      className={cn(
        "sticky top-0 z-sticky w-full flex flex-row justify-center items-center py-3 px-4 h-16 bg-background-tint-01",
        className
      )}
    >
      {children}
    </header>
  );
}

function AppFooter() {
  const settings = useSettingsContext();

  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${
      settings?.webVersion || "dev"
    }](https://www.onyx.app/) - Open Source AI Platform`;

  return (
    <footer className="w-full flex flex-row justify-center items-center gap-2 pb-2">
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
 * Wraps chat pages with custom footer.
 *
 * Layout Structure:
 * ```
 * ┌──────────────────────────────────┐
 * │                                  │
 * │ Content Area (children)          │
 * │                                  │
 * ├──────────────────────────────────┤
 * │ Footer (custom disclaimer)       │
 * └──────────────────────────────────┘
 * ```
 *
 * Note: ChatHeader is rendered inside ChatUI's scroll container
 * for sticky behavior, not in this root component.
 */
export interface AppRootProps {
  children?: React.ReactNode;
}

function AppRoot({ children }: AppRootProps) {
  return (
    /* NOTE: Some elements, markdown tables in particular, refer to this `@container` in order to
      breakout of their immediate containers using cqw units.
    */
    <div className="@container flex flex-col h-full w-full">
      <div className="flex-1 overflow-auto h-full w-full">{children}</div>
      <AppFooter />
    </div>
  );
}

export { AppRoot as Root, StickyHeader };
