"use client";

import { useState } from "react";
import { ensureHrefProtocol, noProp } from "@/lib/utils";
import { cn } from "@opal/utils";
import type { Components } from "react-markdown";
import Text from "@/refresh-components/texts/Text";
import { Button, LineItemButton, OpenButton, Popover } from "@opal/components";
import { SvgBubbleText, SvgSearchMenu, SvgSidebar } from "@opal/icons";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { useIsSearchModeAvailable } from "@/lib/settings/hooks";
import { useCustomFooterContent } from "@/lib/app/hooks";
import { useAppPosition } from "@/lib/position/hooks";
import type { AppMode } from "@/providers/QueryControllerProvider";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { useSidebarState } from "@opal/layouts";
import useScreenSize from "@/hooks/useScreenSize";

const footerMarkdownComponents = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <Text as="p" text03 secondaryAction className="my-0! text-center">
      {children}
    </Text>
  ),
  a: ({
    href,
    className,
    children,
    ...rest
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => {
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

/**
 * Lightweight chrome overlay for the NRF page.
 *
 * Renders only the search/chat mode toggle (top-left) and footer (bottom),
 * absolutely positioned so they float transparently over NRFPage's own
 * background. This avoids pulling in the full AppLayouts.Root Header which
 * carries heavy state management (share/delete/move modals) that the
 * extension doesn't need.
 */
export default function NRFChrome() {
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const { state, setAppMode } = useQueryController();
  const isSearchModeAvailable = useIsSearchModeAvailable();
  const { isMobile } = useScreenSize();
  const { setFolded } = useSidebarState();
  const appPosition = useAppPosition();
  const [modePopoverOpen, setModePopoverOpen] = useState(false);

  const effectiveMode: AppMode =
    appPosition.isNewSession() && state.phase === "idle"
      ? state.appMode
      : "chat";

  const customFooterContent = useCustomFooterContent();

  const showModeToggle =
    businessTier &&
    isSearchModeAvailable &&
    appPosition.isNewSession() &&
    state.phase === "idle";

  const showHeader = isMobile || showModeToggle;

  return (
    <>
      {/* Header chrome — top-left, mirrors position of settings button at top-right */}
      {showHeader && (
        <div className="absolute top-0 left-0 p-4 z-10 flex flex-row items-center gap-2">
          {isMobile && (
            <Button
              prominence="internal"
              icon={SvgSidebar}
              aria-label="Open Sidebar"
              onClick={() => setFolded(false)}
            />
          )}
          {showModeToggle && (
            <Popover open={modePopoverOpen} onOpenChange={setModePopoverOpen}>
              <Popover.Trigger asChild>
                <OpenButton
                  icon={
                    effectiveMode === "search" ? SvgSearchMenu : SvgBubbleText
                  }
                >
                  {effectiveMode === "search" ? "Search" : "Chat"}
                </OpenButton>
              </Popover.Trigger>
              <Popover.Content align="start" width="lg">
                <Popover.Menu>
                  <LineItemButton
                    sizePreset="main-ui"
                    rounding={2}
                    icon={SvgSearchMenu}
                    state={effectiveMode === "search" ? "selected" : "empty"}
                    description="Quick search for documents"
                    onClick={noProp(() => {
                      setAppMode("search");
                      setModePopoverOpen(false);
                    })}
                    title="Search"
                  />
                  <LineItemButton
                    sizePreset="main-ui"
                    rounding={2}
                    icon={SvgBubbleText}
                    state={effectiveMode === "chat" ? "selected" : "empty"}
                    description="Conversation and research"
                    onClick={noProp(() => {
                      setAppMode("chat");
                      setModePopoverOpen(false);
                    })}
                    title="Chat"
                  />
                </Popover.Menu>
              </Popover.Content>
            </Popover>
          )}
        </div>
      )}

      {/* Footer — bottom-center, transparent background */}
      <footer className="absolute bottom-0 left-0 w-full z-10 flex flex-row justify-center items-center gap-2 px-2 pb-2 pointer-events-auto">
        <MinimalMarkdown
          content={customFooterContent}
          className="max-w-full text-center"
          components={footerMarkdownComponents}
        />
      </footer>
    </>
  );
}
