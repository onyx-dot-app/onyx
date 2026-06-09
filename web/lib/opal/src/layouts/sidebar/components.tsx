"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
  useLayoutEffect,
  type Dispatch,
  type SetStateAction,
} from "react";
import { usePathname } from "next/navigation";
import { cn } from "@opal/utils";
import {
  RootLayoutFoldedContext,
  useSidebarFolded,
} from "@opal/layouts/root/components";
import useScreenSize from "@opal/hooks/useScreenSize";
import SidebarWrapper from "@opal/layouts/sidebar/SidebarWrapper";
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

  const setFolded: Dispatch<SetStateAction<boolean>> = (value) => {
    setFoldedInternal((prev) => {
      const newState = typeof value === "function" ? value(prev) : value;
      onFoldedChange?.(newState);
      return newState;
    });
  };

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

interface SidebarRootProps {
  /**
   * Whether the sidebar supports folding on desktop.
   * When `false` (the default), the sidebar is always expanded on desktop and
   * the fold button is hidden. Mobile overlay behavior is always enabled
   * regardless of this prop.
   */
  foldable?: boolean;
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

  const inner = (
    <div className="flex flex-col min-h-0 h-full gap-3">{children}</div>
  );

  if (isMobile) {
    return (
      <RootLayoutFoldedContext.Provider value={false}>
        <div
          className={cn(
            "fixed inset-y-0 left-0 z-50 transition-transform duration-200",
            folded ? "-translate-x-full" : "translate-x-0"
          )}
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

        {/* Backdrop — closes the sidebar when anything outside it is tapped */}
        <div
          className={cn(
            "fixed inset-0 z-40 bg-mask-03 backdrop-blur-03 transition-opacity duration-200",
            folded
              ? "opacity-0 pointer-events-none"
              : "opacity-100 pointer-events-auto"
          )}
          onClick={closeSidebar}
        />
      </RootLayoutFoldedContext.Provider>
    );
  }

  if (isMediumScreen) {
    return (
      <RootLayoutFoldedContext.Provider value={folded}>
        {/* Spacer reserves the folded sidebar width in the flex layout */}
        <div className="shrink-0 w-(--sidebar-width-folded)" />

        {/* Sidebar — fixed so it overlays content when expanded */}
        <div className="fixed inset-y-0 left-0 z-50">
          <SidebarWrapper
            folded={folded}
            onFoldClick={toggleSidebar}
            logo={logo}
            showLogoWhenFolded={showLogoWhenFolded}
          >
            {inner}
          </SidebarWrapper>
        </div>

        {/* Backdrop when expanded — blur only, no tint */}
        <div
          className={cn(
            "fixed inset-0 z-40 backdrop-blur-03 transition-opacity duration-200",
            folded
              ? "opacity-0 pointer-events-none"
              : "opacity-100 pointer-events-auto"
          )}
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
  return <div className="px-2">{children}</div>;
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
    <div
      className={cn(
        "relative flex-1 min-h-0 overflow-y-hidden flex flex-col",
        folded && "hidden"
      )}
    >
      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto flex flex-col"
      >
        <div className={cn("flex-1 flex flex-col gap-3 px-2")}>{children}</div>
        <div style={{ minHeight: "2rem" }} />
      </div>
      <div
        className="absolute bottom-0 left-0 right-0 h-4 z-20 pointer-events-none"
        style={{
          background: `linear-gradient(to bottom, transparent, var(--background-tint-02))`,
        }}
      />
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
  return <div className="px-2">{children}</div>;
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
