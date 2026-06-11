"use client";

import "@opal/layouts/sidebar/styles.css";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";
import { usePathname } from "next/navigation";
import { Button, Spacer, Text } from "@opal/components";
import { Disabled, Hoverable } from "@opal/core";
import { SvgSidebar } from "@opal/icons";
import type { RichStr } from "@opal/types";
import { useSidebarState } from "@opal/layouts/root/components";
import useScreenSize from "@opal/hooks/useScreenSize";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SCROLL_POSITION_PREFIX = "opal-sidebar-scroll-";

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

const SidebarFoldableContext = createContext(false);

interface SidebarRootProps {
  /**
   * Whether the sidebar supports folding on desktop.
   * When `false` (the default), the sidebar is always expanded on desktop and
   * the fold button is hidden. Mobile overlay behavior is always enabled
   * regardless of this prop.
   */
  foldable?: boolean;
  children: React.ReactNode;
}

function SidebarRoot({ foldable = false, children }: SidebarRootProps) {
  const { isMobile, isMediumScreen } = useScreenSize();
  const { folded, setFolded } = useSidebarState();

  const closeSidebar = useCallback(() => setFolded(true), [setFolded]);

  useEffect(() => {
    if (!isMobile && !isMediumScreen && !foldable) {
      setFolded(false);
    }
  }, [isMobile, isMediumScreen, foldable, setFolded]);

  const foldedAttr = String(folded);
  const inner = <div className="opal-sidebar-root__inner">{children}</div>;

  if (isMobile) {
    return (
      <SidebarFoldableContext.Provider value={true}>
        <div
          className="opal-sidebar-root__overlay"
          data-variant="mobile"
          data-folded={foldedAttr}
        >
          {inner}
        </div>
        <div
          className="opal-sidebar-root__backdrop"
          data-variant="mobile"
          data-folded={foldedAttr}
          onClick={closeSidebar}
        />
      </SidebarFoldableContext.Provider>
    );
  }

  if (isMediumScreen) {
    return (
      <SidebarFoldableContext.Provider value={true}>
        <div className="opal-sidebar-root__spacer" />
        <div
          className="opal-sidebar-root__overlay"
          data-variant="medium"
          data-folded={foldedAttr}
        >
          {inner}
        </div>
        <div
          className="opal-sidebar-root__backdrop"
          data-variant="medium"
          data-folded={foldedAttr}
          onClick={closeSidebar}
        />
      </SidebarFoldableContext.Provider>
    );
  }

  return (
    <SidebarFoldableContext.Provider value={foldable}>
      <div
        className="opal-sidebar-root__column"
        data-folded={foldable ? foldedAttr : undefined}
      >
        {inner}
      </div>
    </SidebarFoldableContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Header — topbar (logo + fold button) with optional pinned content below
// ---------------------------------------------------------------------------

interface SidebarHeaderProps {
  logo?: (folded: boolean | undefined) => React.ReactNode;
  /**
   * When `true` (default), the logo is shown in the folded state with a
   * hover-to-reveal fold button. When `false`, only the fold button is shown
   * when folded.
   */
  showLogoWhenFolded?: boolean;
  children?: React.ReactNode;
}

function SidebarHeader({
  logo,
  showLogoWhenFolded = true,
  children,
}: SidebarHeaderProps) {
  const foldable = useContext(SidebarFoldableContext);
  const { folded, setFolded } = useSidebarState();
  const toggleFolded = useCallback(
    () => setFolded((prev) => !prev),
    [setFolded]
  );

  const closeButton = useMemo(
    () => (
      <div className="px-1">
        <Button
          icon={SvgSidebar}
          prominence="tertiary"
          tooltip={folded ? "Open Sidebar" : "Close Sidebar"}
          tooltipSide={folded ? "right" : "bottom"}
          size="md"
          onClick={toggleFolded}
        />
      </div>
    ),
    [folded, toggleFolded]
  );

  if (logo == null && !children) return null;

  const logoEl = logo != null ? logo(foldable ? folded : undefined) : null;

  return (
    <div className="opal-sidebar-header">
      {logo != null && (
        <div className="opal-sidebar-header__topbar">
          {!foldable ? (
            logoEl
          ) : folded && showLogoWhenFolded && logoEl ? (
            <>
              <div className="opal-sidebar-root__logo-default">{logoEl}</div>
              <div className="opal-sidebar-root__logo-hover">{closeButton}</div>
            </>
          ) : folded ? (
            closeButton
          ) : (
            <>
              {logoEl}
              {closeButton}
            </>
          )}
        </div>
      )}
      {children && (
        <div className="opal-sidebar-header__content">{children}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Body — scrollable content area with scroll-position persistence
// ---------------------------------------------------------------------------

interface SidebarBodyProps {
  /**
   * Unique key to enable scroll position persistence across navigation.
   * (e.g., "admin-sidebar", "app-sidebar").
   */
  scrollKey: string;
  children?: React.ReactNode;
}

function SidebarBody({ scrollKey, children }: SidebarBodyProps) {
  const { folded } = useSidebarState();
  const scrollRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  useEffect(() => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const storageKey = `${SCROLL_POSITION_PREFIX}${scrollKey}`;
    const handleScroll = () => {
      sessionStorage.setItem(storageKey, scrollElement.scrollTop.toString());
    };

    scrollElement.addEventListener("scroll", handleScroll, { passive: true });
    return () => scrollElement.removeEventListener("scroll", handleScroll);
  }, [scrollKey]);

  useLayoutEffect(() => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const storageKey = `${SCROLL_POSITION_PREFIX}${scrollKey}`;
    const savedPosition = parseInt(
      sessionStorage.getItem(storageKey) || "0",
      10
    );
    scrollElement.scrollTop = savedPosition;
  }, [pathname, scrollKey]);

  return (
    <div className="opal-sidebar-body">
      <div ref={scrollRef} className="opal-sidebar-body__scroll">
        <div
          className="opal-sidebar-body__content"
          data-folded={String(folded)}
        >
          {children}
        </div>
        <div className="opal-sidebar-body__spacer" />
      </div>
      <div className="opal-sidebar-body__fade" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Footer — pinned content below the scroll area
// ---------------------------------------------------------------------------

interface SidebarFooterProps {
  children?: React.ReactNode;
}

function SidebarFooter({ children }: SidebarFooterProps) {
  return <div className="opal-sidebar-footer">{children}</div>;
}

// ---------------------------------------------------------------------------
// Section — titled group within the scrollable body
// ---------------------------------------------------------------------------

interface SidebarSectionProps {
  title?: string | RichStr;
  /** Optional action shown on hover, e.g. a "+" button. */
  action?: React.ReactNode;
  /** When true, dims the section header to indicate it is unavailable. */
  disabled?: boolean;

  children?: React.ReactNode;
}

function SidebarSection({
  title,
  action,
  disabled,
  children,
}: SidebarSectionProps) {
  return (
    <div className="flex flex-col">
      {title ? (
        <Hoverable.Root group="sidebar-section">
          <Disabled disabled={disabled}>
            <div className="opal-sidebar-section__header">
              <div className="opal-sidebar-section__title">
                <Text font="secondary-body" color="text-02">
                  {title}
                </Text>
              </div>
              {action && (
                <Hoverable.Item group="sidebar-section">
                  {action}
                </Hoverable.Item>
              )}
            </div>
          </Disabled>
        </Hoverable.Root>
      ) : (
        <Spacer rem={0.5} />
      )}
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  SidebarRoot as Root,
  SidebarHeader as Header,
  SidebarBody as Body,
  SidebarFooter as Footer,
  SidebarSection as Section,
};
export type { SidebarRootProps };
