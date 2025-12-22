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
 * import { AppPageLayout } from "@/layouts/app-pages";
 *
 * export default function ChatPage() {
 *   const settings = useCombinedSettings();
 *   const chatSession = useCurrentChatSession();
 *
 *   return (
 *     <AppPageLayout settings={settings} chatSession={chatSession}>
 *       <ChatInterface />
 *     </AppPageLayout>
 *   );
 * }
 *
 * // With custom className
 * <AppPageLayout
 *   settings={settings}
 *   chatSession={chatSession}
 *   className="bg-custom-background"
 * >
 *   <ChatInterface />
 * </AppPageLayout>
 * ```
 */

"use client";

import { ChatSession } from "@/app/chat/interfaces";
import { cn } from "@/lib/utils";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import ChatHeader from "./ChatHeader";
import ChatFooter from "./ChatFooter";

/**
 * App Page Layout Props
 *
 * @property settings - Combined enterprise settings for white-labeling (header/footer content)
 * @property chatSession - Current chat session for action buttons (share, move, delete)
 * @property className - Additional CSS classes for the content area
 */
export interface AppPageLayoutProps
  extends React.HtmlHTMLAttributes<HTMLDivElement> {
  settings: CombinedSettings | null;
  chatSession: ChatSession | null;
}

/**
 * App Page Layout Component
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
 * - "Share Chat" button (visible when not showing centered input)
 * - Kebab menu with "Move to Project" and "Delete" options
 * - Move confirmation modal for custom agent chats
 * - Delete confirmation modal
 * - Renders custom footer disclaimer from enterprise settings
 *
 * State Management:
 * - Manages multiple modals (share, move, delete)
 * - Handles project search/filtering in move modal
 * - Integrates with projects context for chat operations
 *
 * @example
 * ```tsx
 * // Basic usage in a chat page
 * <AppPageLayout settings={settings} chatSession={currentSession}>
 *   <ChatInterface />
 * </AppPageLayout>
 *
 * // The header will show:
 * // - Mobile: Sidebar toggle button
 * // - Desktop: Share button + kebab menu
 * // - Custom header text (if configured)
 *
 * // The footer will show custom disclaimer (if configured)
 * ```
 */
export function AppPageLayout({
  settings,
  chatSession,
  className,
  ...rest
}: AppPageLayoutProps) {
  return (
    <div className="flex flex-col h-full w-full">
      <ChatHeader settings={settings} chatSession={chatSession} />
      <div className={cn("flex-1 overflow-auto", className)} {...rest} />
      <ChatFooter settings={settings} chatSession={chatSession} />
    </div>
  );
}
