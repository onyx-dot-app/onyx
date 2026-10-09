"use client";

import { useEffect, useRef, useState } from "react";
import { ensureHrefProtocol } from "@/lib/utils";
import { cn } from "@opal/utils";
import type { Components } from "react-markdown";
import Text from "@/refresh-components/texts/Text";
import { Button, Dropdown, OpenButton } from "@opal/components";
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
import { useTranslations } from "next-intl";

const NRF_FOOTER_HEIGHT_VAR = "--nrf-footer-height";

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
  const t = useTranslations("chat");
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const { state, setAppMode } = useQueryController();
  const isSearchModeAvailable = useIsSearchModeAvailable();
  const { isMobile } = useScreenSize();
  const { setFolded } = useSidebarState();
  const appPosition = useAppPosition();
  const [modePopoverOpen, setModePopoverOpen] = useState(false);
  const footerRef = useRef<HTMLElement>(null);

  // Publishes the footer height so NRFPage can keep scrollable content clear of it
  useEffect(() => {
    const footer = footerRef.current;
    const host = footer?.parentElement;
    if (!footer || !host) return;

    const update = () =>
      host.style.setProperty(
        NRF_FOOTER_HEIGHT_VAR,
        `${footer.getBoundingClientRect().height}px`
      );
    update();

    const observer = new ResizeObserver(update);
    observer.observe(footer);
    return () => {
      observer.disconnect();
      host.style.removeProperty(NRF_FOOTER_HEIGHT_VAR);
    };
  }, []);

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
        <div className="absolute top-0 start-0 p-4 z-10 flex flex-row items-center gap-2">
          {isMobile && (
            <Button
              prominence="internal"
              icon={SvgSidebar}
              aria-label={t("appChrome.openSidebar.ariaLabel")}
              onClick={() => setFolded(false)}
            />
          )}
          {showModeToggle && (
            <Dropdown open={modePopoverOpen} onOpenChange={setModePopoverOpen}>
              <Dropdown.Trigger asChild>
                <OpenButton
                  aria-label={t("appChrome.modeButton.ariaLabel")}
                  icon={
                    effectiveMode === "search" ? SvgSearchMenu : SvgBubbleText
                  }
                  interaction={modePopoverOpen ? "hover" : "rest"}
                >
                  {effectiveMode === "search"
                    ? t("appChrome.mode.search.label")
                    : t("appChrome.mode.chat.label")}
                </OpenButton>
              </Dropdown.Trigger>
              <Dropdown.Data
                label={t("appChrome.modeButton.ariaLabel")}
                value={effectiveMode}
                onSelect={(option) =>
                  setAppMode(option.value === "search" ? "search" : "chat")
                }
                items={[
                  {
                    kind: "option",
                    value: "search",
                    icon: SvgSearchMenu,
                    title: t("appChrome.mode.search.label"),
                    description: t("appChrome.mode.search.description"),
                  },
                  {
                    kind: "option",
                    value: "chat",
                    icon: SvgBubbleText,
                    title: t("appChrome.mode.chat.label"),
                    description: t("appChrome.mode.chat.description"),
                  },
                ]}
              />
            </Dropdown>
          )}
        </div>
      )}

      {/* Footer — bottom-center, transparent background */}
      <footer
        ref={footerRef}
        className="absolute bottom-0 start-0 w-full z-10 flex flex-row justify-center items-center gap-2 px-2 pb-2 pointer-events-auto"
      >
        <MinimalMarkdown
          content={customFooterContent}
          className="max-w-full text-center"
          components={footerMarkdownComponents}
        />
      </footer>
    </>
  );
}
