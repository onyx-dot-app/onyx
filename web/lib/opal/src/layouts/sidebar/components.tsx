"use client";

import "@opal/layouts/sidebar/styles.css";
import {
  createContext,
  useCallback,
  useContext,
  useState,
  useEffect,
  useRef,
  useLayoutEffect,
  useMemo,
  type Dispatch,
  type SetStateAction,
} from "react";
import { usePathname } from "next/navigation";
import { Button, Text } from "@opal/components";
import { Disabled, Hoverable } from "@opal/core";
import { SvgSidebar } from "@opal/icons";
import type { RichStr } from "@opal/types";
import {
  RootLayoutFoldedContext,
  useSidebarFolded,
} from "@opal/layouts/root/components";
import useScreenSize from "@opal/hooks/useScreenSize";
export { useSidebarFolded } from "@opal/layouts/root/components";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SCROLL_POSITION_PREFIX = "opal-sidebar-scroll-";

// ---------------------------------------------------------------------------
// State provider — sidebar fold state with Cmd/Ctrl+E keyboard shortcut
// ---------------------------------------------------------------------------

interface SidebarStateContextType {
  folded: boolean;
  setFolded: Dispatch<SetStateAction<boolean>>;
}

const SidebarStateContext = createContext<SidebarStateContextType | undefined>(
  undefined
);

interface SidebarStateProviderProps {
  /** Initial fold state, typically read from a persisted cookie by the app. */
  defaultFolded?: boolean;
  /** Called whenever the fold state changes, e.g. to persist to a cookie. */
  onFoldedChange?: (folded: boolean) => void;
  children: React.ReactNode;
}

function SidebarStateProvider({
  defaultFolded = false,
  onFoldedChange,
  children,
}: SidebarStateProviderProps) {
  const [folded, setFoldedInternal] = useState(defaultFolded);

  // Keep a ref so the effect below always sees the latest callback without
  // needing it as a dependency (avoids unnecessary effect re-runs).
  const onFoldedChangeRef = useRef(onFoldedChange);
  onFoldedChangeRef.current = onFoldedChange;

  const setFolded: Dispatch<SetStateAction<boolean>> = (value) => {
    setFoldedInternal((prev) =>
      typeof value === "function" ? value(prev) : value
    );
  };

  // Notify after state commits rather than inside the updater, keeping the
  // updater pure and safe under React's StrictMode double-invocation.
  const isMounted = useRef(false);
  useEffect(() => {
    if (!isMounted.current) {
      isMounted.current = true;
      return;
    }
    onFoldedChangeRef.current?.(folded);
  }, [folded]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const isMac = navigator.userAgent.toLowerCase().includes("mac");
      const isModifierPressed = isMac ? event.metaKey : event.ctrlKey;
      if (!isModifierPressed || event.key !== "e") return;

      event.preventDefault();
      setFolded((prev) => !prev);
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  return (
    <SidebarStateContext.Provider value={{ folded, setFolded }}>
      {children}
    </SidebarStateContext.Provider>
  );
}

/**
 * Returns the global sidebar fold state and setter.
 * Must be used within a `SidebarStateProvider`.
 */
export function useSidebarState(): SidebarStateContextType {
  const context = useContext(SidebarStateContext);
  if (context === undefined) {
    throw new Error(
      "useSidebarState must be used within a SidebarStateProvider"
    );
  }
  return context;
}

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

  const contentFolded = !isMobile && foldable ? folded : false;
  const foldedAttr = String(folded);
  const inner = <div className="opal-sidebar-root__inner">{children}</div>;

  if (isMobile) {
    return (
      <SidebarFoldableContext.Provider value={foldable}>
        <RootLayoutFoldedContext.Provider value={false}>
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
        </RootLayoutFoldedContext.Provider>
      </SidebarFoldableContext.Provider>
    );
  }

  if (isMediumScreen) {
    return (
      <SidebarFoldableContext.Provider value={foldable}>
        <RootLayoutFoldedContext.Provider value={folded}>
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
        </RootLayoutFoldedContext.Provider>
      </SidebarFoldableContext.Provider>
    );
  }

  return (
    <SidebarFoldableContext.Provider value={foldable}>
      <RootLayoutFoldedContext.Provider value={contentFolded}>
        <div
          className="opal-sidebar-root__column"
          data-folded={foldable ? foldedAttr : undefined}
        >
          {inner}
        </div>
      </RootLayoutFoldedContext.Provider>
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

  if (!logo && !children) return null;

  const logoEl = logo ? logo(foldable ? folded : undefined) : null;

  return (
    <div className="opal-sidebar-header">
      {logo && (
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
  const folded = useSidebarFolded();
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
  if (!children) return null;
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
}

function SidebarSection({ title, action, disabled }: SidebarSectionProps) {
  return (
    <Hoverable.Root group="sidebar-section">
      <Disabled disabled={disabled}>
        <div className="opal-sidebar-section__header">
          <div className="opal-sidebar-section__title">
            <Text font="secondary-body" color="text-02">
              {title}
            </Text>
          </div>
          {action && (
            <Hoverable.Item group="sidebar-section">{action}</Hoverable.Item>
          )}
        </div>
      </Disabled>
    </Hoverable.Root>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  SidebarStateProvider as StateProvider,
  SidebarRoot as Root,
  SidebarHeader as Header,
  SidebarBody as Body,
  SidebarFooter as Footer,
  SidebarSection as Section,
};
export type { SidebarRootProps };
