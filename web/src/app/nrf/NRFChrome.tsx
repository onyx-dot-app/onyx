"use client";

import { useState } from "react";
import { cn, ensureHrefProtocol, noProp } from "@/lib/utils";
import type { Components } from "react-markdown";
import Text from "@/refresh-components/texts/Text";
import Popover from "@/refresh-components/Popover";
import { OpenButton } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgBubbleText, SvgSearchMenu, SvgSidebar } from "@opal/icons";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { AppMode, useAppMode } from "@/providers/AppModeProvider";
import useAppFocus from "@/hooks/useAppFocus";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { useAppSidebarContext } from "@/providers/AppSidebarProvider";
import useScreenSize from "@/hooks/useScreenSize";

const footerMarkdownComponents = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <Text as="p" text03 secondaryAction className="!my-0 text-center">
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
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const { appMode, setAppMode } = useAppMode();
  const settings = useSettingsContext();
  const { isMobile } = useScreenSize();
  const { setFolded } = useAppSidebarContext();
  const appFocus = useAppFocus();
  const { classification } = useQueryController();
  const [modePopoverOpen, setModePopoverOpen] = useState(false);

  const effectiveMode: AppMode = appFocus.isNewSession() ? appMode : "chat";

  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${
      settings?.webVersion || "dev"
    }](https://www.onyx.app/) - Open Source AI Platform`;

  const showModeToggle =
    isPaidEnterpriseFeaturesEnabled &&
    settings.isSearchModeAvailable &&
    appFocus.isNewSession() &&
    !classification;

  const showHeader = isMobile || showModeToggle;

  return (
    <>
      {/* Header chrome — top-left, mirrors position of settings button at top-right */}
      {showHeader && (
        <div className="absolute top-0 left-0 p-4 z-10 flex flex-row items-center gap-2">
          {isMobile && (
            <IconButton
              icon={SvgSidebar}
              onClick={() => setFolded(false)}
              internal
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
                  <LineItem
                    icon={SvgSearchMenu}
                    selected={effectiveMode === "search"}
                    description="Quick search for documents"
                    onClick={noProp(() => {
                      setAppMode("search");
                      setModePopoverOpen(false);
                    })}
                  >
                    Search
                  </LineItem>
                  <LineItem
                    icon={SvgBubbleText}
                    selected={effectiveMode === "chat"}
                    description="Conversation and research"
                    onClick={noProp(() => {
                      setAppMode("chat");
                      setModePopoverOpen(false);
                    })}
                  >
                    Chat
                  </LineItem>
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
