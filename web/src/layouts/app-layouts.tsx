/**
 * App Page Layout Component
 *
 * Primary layout component for chat/application pages. Handles white-labeling,
 * chat session actions (share, move, delete), and responsive header/footer rendering.
 *
 * Features:
 * - Custom header/footer content from enterprise settings
 * - Share chat functionality
 * - Move chat to project (with confirmation for custom agents)
 * - Delete chat with confirmation
 * - Mobile-responsive sidebar toggle
 * - Conditional rendering based on chat state
 *
 * @example
 * ```tsx
 * import AppLayouts from "@/layouts/app-layouts";
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
import IconButton from "@/refresh-components/buttons/IconButton";
import useChatSessions from "@/hooks/useChatSessions";
import { useAppSidebarContext } from "@/refresh-components/contexts/AppSidebarContext";
import useScreenSize from "@/hooks/useScreenSize";
import { SvgSidebar } from "@opal/icons";
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
        <Text text03 secondaryAction>
          {children}
        </Text>
      </a>
    );
  },
} satisfies Partial<Components>;

function AppHeader() {
  const settings = useSettingsContext();
  const { isMobile } = useScreenSize();
  const { setFolded } = useAppSidebarContext();
  const { currentChatSessionId } = useChatSessions();

  const customHeaderContent =
    settings?.enterpriseSettings?.custom_header_content;

  // Don't render when there's a chat session - ChatHeader handles that
  if (currentChatSessionId) return null;

  // Only render when on mobile or there's custom header content
  if (!isMobile && !customHeaderContent) return null;

  return (
    <header className="w-full flex flex-row justify-center items-center py-3 px-4 h-16">
      {/* Left - contains the icon-button to fold the AppSidebar on mobile */}
      <div className="flex-1">
        <IconButton
          icon={SvgSidebar}
          onClick={() => setFolded(false)}
          className={cn(!isMobile && "invisible")}
          internal
        />
      </div>

      {/* Center - contains the custom-header-content */}
      <div className="flex-1 flex flex-col items-center overflow-hidden">
        <Text
          as="p"
          text03
          mainUiBody
          className="text-center break-words w-full"
        >
          {customHeaderContent}
        </Text>
      </div>

      {/* Right - empty placeholder for layout balance */}
      <div className="flex-1" />
    </header>
  );
}

function Footer() {
  const settings = useSettingsContext();

  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${
      settings?.webVersion || "dev"
    }](https://www.onyx.app/) - Open Source AI Platform`;

  return (
    <footer className="w-full flex flex-row justify-center items-center gap-2 pb-2 mt-auto">
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
 * Wraps chat pages with white-labeling chrome (custom header/footer) and
 * provides chat session management actions.
 *
 * Layout Structure:
 * ```
 * ┌──────────────────────────────────┐
 * │ Header (custom or with actions)  │
 * ├──────────────────────────────────┤
 * │                                  │
 * │ Content Area (children)          │
 * │                                  │
 * ├──────────────────────────────────┤
 * │ Footer (custom disclaimer)       │
 * └──────────────────────────────────┘
 * ```
 *
 * Features:
 * - Renders custom header content from enterprise settings
 * - Shows sidebar toggle on mobile
 * - "Share Chat" button for current chat session
 * - Kebab menu with "Move to Project" and "Delete" options
 * - Move confirmation modal for custom agent chats
 * - Delete confirmation modal
 * - Renders custom footer disclaimer from enterprise settings
 *
 * State Management:
 * - Manages multiple modals (share, move, delete)
 * - Handles project search/filtering in move modal
 * - Integrates with projects context for chat operations
 * - Uses settings context for white-labeling
 * - Uses chat sessions hook for current session
 *
 * @example
 * ```tsx
 * // Basic usage in a chat page
 * <AppLayouts.Root>
 *   <ChatInterface />
 * </AppLayouts.Root>
 *
 * // The header will show:
 * // - Mobile: Sidebar toggle button
 * // - Desktop: Share button + kebab menu (when chat session exists)
 * // - Custom header text (if configured)
 *
 * // The footer will show custom disclaimer (if configured)
 * ```
 */
export interface AppRootProps {
  /**
   * @deprecated This prop should rarely be used. Prefer letting the Footer render.
   */
  disableFooter?: boolean;
  children?: React.ReactNode;
}

function AppRoot({ children, disableFooter }: AppRootProps) {
  return (
    /* NOTE: Some elements, markdown tables in particular, refer to this `@container` in order to
      breakout of their immediate containers using cqw units.
    */
    <div className="@container flex flex-col h-full w-full">
      <AppHeader />
      <div className="flex-1 overflow-auto h-full w-full">{children}</div>
      {!disableFooter && <Footer />}
    </div>
  );
}

/**
 * Sticky Header Wrapper
 *
 * A layout component that provides sticky positioning for header content.
 * Use this to wrap any header content that should stick to the top of a scroll container.
 *
 * @example
 * ```tsx
 * <ChatScrollContainer>
 *   <AppLayouts.StickyHeader>
 *     <ChatHeader />
 *   </AppLayouts.StickyHeader>
 *   <MessageList />
 * </ChatScrollContainer>
 * ```
 */
export interface StickyHeaderProps {
  children?: React.ReactNode;
  className?: string;
}

function StickyHeader({ children, className }: StickyHeaderProps) {
  return (
    <header className={cn("sticky top-0 z-sticky w-full", className)}>
      {children}
    </header>
  );
}

export { AppRoot as Root, StickyHeader, Footer };
