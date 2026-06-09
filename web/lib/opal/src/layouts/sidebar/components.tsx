"use client";

import "@opal/layouts/sidebar/styles.css";
import {
  createContext,
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
import { cn } from "@opal/utils";
import { Button } from "@opal/components";
import { SvgSidebar } from "@opal/icons";
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
// SidebarWrapper — structural chrome shared by Root and direct callers
// ---------------------------------------------------------------------------

export interface SidebarWrapperProps {
  folded?: boolean;
  onFoldClick?: () => void;
  /**
   * Render function for the logo/brand area. Receives the current fold state
   * so the logo can adapt its appearance (e.g. icon-only vs full wordmark).
   */
  logo?: (folded: boolean | undefined) => React.ReactNode;
  /**
   * When `true` (default), the logo is shown in the folded state with a
   * hover-to-reveal close button. When `false`, only the close button is
   * shown when folded.
   */
  showLogoWhenFolded?: boolean;
  children?: React.ReactNode;
}

export function SidebarWrapper({
  folded,
  onFoldClick,
  logo,
  showLogoWhenFolded = true,
  children,
}: SidebarWrapperProps) {
  const closeButton = useMemo(
    () => (
      <div className="px-1">
        <Button
          icon={SvgSidebar}
          prominence="tertiary"
          tooltip={folded ? "Open Sidebar" : "Close Sidebar"}
          tooltipSide={folded ? "right" : "bottom"}
          size="md"
          onClick={onFoldClick}
        />
      </div>
    ),
    [folded, onFoldClick]
  );

  const logoEl = logo ? logo(folded) : null;
  const foldedAttr = folded === undefined ? undefined : String(folded);

  return (
    <div className="opal-sidebar-wrapper">
      <div className="opal-sidebar-wrapper__inner" data-folded={foldedAttr}>
        <div className="opal-sidebar-wrapper__topbar">
          {folded === undefined ? (
            logoEl
          ) : folded && showLogoWhenFolded && logoEl ? (
            <>
              <div className="opal-sidebar-wrapper__logo-default">{logoEl}</div>
              <div className="opal-sidebar-wrapper__logo-hover">
                {closeButton}
              </div>
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
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

interface SidebarRootProps {
  /**
   * Whether the sidebar supports folding on desktop.
   * When `false` (the default), the sidebar is always expanded on desktop and
   * the fold button is hidden. Mobile overlay behavior is always enabled
   * regardless of this prop.
   */
  foldable?: boolean;
  logo?: (folded: boolean | undefined) => React.ReactNode;
  showLogoWhenFolded?: boolean;
  children: React.ReactNode;
}

function SidebarRoot({
  foldable = false,
  logo,
  showLogoWhenFolded = true,
  children,
}: SidebarRootProps) {
  const { isMobile, isMediumScreen } = useScreenSize();
  const { folded, setFolded } = useSidebarState();

  function closeSidebar() {
    setFolded(true);
  }
  function toggleSidebar() {
    setFolded((prev) => !prev);
  }

  const contentFolded = !isMobile && foldable ? folded : false;
  const foldedAttr = String(folded);

  const inner = <div className="opal-sidebar-root__inner">{children}</div>;

  if (isMobile) {
    return (
      <RootLayoutFoldedContext.Provider value={false}>
        <div
          className="opal-sidebar-root__overlay"
          data-variant="mobile"
          data-folded={foldedAttr}
        >
          <SidebarWrapper
            folded={false}
            onFoldClick={closeSidebar}
            logo={logo}
            showLogoWhenFolded={showLogoWhenFolded}
          >
            {inner}
          </SidebarWrapper>
        </div>

        <div
          className="opal-sidebar-root__backdrop"
          data-variant="mobile"
          data-folded={foldedAttr}
          onClick={closeSidebar}
        />
      </RootLayoutFoldedContext.Provider>
    );
  }

  if (isMediumScreen) {
    return (
      <RootLayoutFoldedContext.Provider value={folded}>
        <div className="opal-sidebar-root__spacer" />

        <div className="opal-sidebar-root__overlay" data-variant="medium">
          <SidebarWrapper
            folded={folded}
            onFoldClick={toggleSidebar}
            logo={logo}
            showLogoWhenFolded={showLogoWhenFolded}
          >
            {inner}
          </SidebarWrapper>
        </div>

        <div
          className="opal-sidebar-root__backdrop"
          data-variant="medium"
          data-folded={foldedAttr}
          onClick={closeSidebar}
        />
      </RootLayoutFoldedContext.Provider>
    );
  }

  return (
    <RootLayoutFoldedContext.Provider value={contentFolded}>
      <SidebarWrapper
        folded={foldable ? folded : undefined}
        onFoldClick={foldable ? toggleSidebar : undefined}
        logo={logo}
        showLogoWhenFolded={showLogoWhenFolded}
      >
        {inner}
      </SidebarWrapper>
    </RootLayoutFoldedContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Header — pinned content above the scroll area
// ---------------------------------------------------------------------------

interface SidebarHeaderProps {
  children?: React.ReactNode;
}

function SidebarHeader({ children }: SidebarHeaderProps) {
  if (!children) return null;
  return <div className="opal-sidebar-header">{children}</div>;
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
// Exports
// ---------------------------------------------------------------------------

export {
  SidebarStateProvider as StateProvider,
  SidebarRoot as Root,
  SidebarHeader as Header,
  SidebarBody as Body,
  SidebarFooter as Footer,
};
