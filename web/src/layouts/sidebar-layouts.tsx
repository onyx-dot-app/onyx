"use client";

/**
 * Sidebar Layout Components
 *
 * Provides composable layout primitives for app and admin sidebars with mobile
 * overlay support and optional desktop folding.
 *
 * @example
 * ```tsx
 * import * as SidebarLayouts from "@/layouts/sidebar-layouts";
 * import { useSidebarState, useSidebarFolded } from "@/layouts/sidebar-layouts";
 *
 * function MySidebar() {
 *   const { folded, setFolded } = useSidebarState();
 *   const contentFolded = useSidebarFolded();
 *
 *   return (
 *     <SidebarLayouts.Root folded={folded} onFoldChange={setFolded} foldable>
 *       <SidebarLayouts.Header>
 *         <NewSessionButton folded={contentFolded} />
 *       </SidebarLayouts.Header>
 *       <SidebarLayouts.Body scrollKey="my-sidebar">
 *         {contentFolded ? null : <SectionContent />}
 *       </SidebarLayouts.Body>
 *       <SidebarLayouts.Footer>
 *         <UserAvatar />
 *       </SidebarLayouts.Footer>
 *     </SidebarLayouts.Root>
 *   );
 * }
 * ```
 */

import {
  createContext,
  useContext,
  useCallback,
  useState,
  useEffect,
  type Dispatch,
  type SetStateAction,
} from "react";
import Cookies from "js-cookie";
import { cn } from "@/lib/utils";
import { SIDEBAR_TOGGLED_COOKIE_NAME } from "@/components/resizable/constants";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import OverflowDiv from "@/refresh-components/OverflowDiv";
import useScreenSize from "@/hooks/useScreenSize";

// ---------------------------------------------------------------------------
// State provider — persistent sidebar fold state with keyboard shortcut
// ---------------------------------------------------------------------------

function setFoldedCookie(folded: boolean) {
  const foldedAsString = folded.toString();
  Cookies.set(SIDEBAR_TOGGLED_COOKIE_NAME, foldedAsString, { expires: 365 });
  if (typeof window !== "undefined") {
    localStorage.setItem(SIDEBAR_TOGGLED_COOKIE_NAME, foldedAsString);
  }
}

interface SidebarStateContextType {
  folded: boolean;
  setFolded: Dispatch<SetStateAction<boolean>>;
}

const SidebarStateContext = createContext<SidebarStateContextType | undefined>(
  undefined
);

interface SidebarStateProviderProps {
  children: React.ReactNode;
}

function SidebarStateProvider({ children }: SidebarStateProviderProps) {
  const [folded, setFoldedInternal] = useState(false);

  useEffect(() => {
    const stored =
      Cookies.get(SIDEBAR_TOGGLED_COOKIE_NAME) ??
      localStorage.getItem(SIDEBAR_TOGGLED_COOKIE_NAME);
    if (stored === "true") {
      setFoldedInternal(true);
    }
  }, []);

  const setFolded: Dispatch<SetStateAction<boolean>> = (value) => {
    setFoldedInternal((prev) => {
      const newState = typeof value === "function" ? value(prev) : value;
      setFoldedCookie(newState);
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
// Fold context
// ---------------------------------------------------------------------------

const SidebarFoldedContext = createContext(false);

/**
 * Returns whether the sidebar content should render in its folded (narrow)
 * state. On mobile, this is always `false` because the overlay pattern handles
 * visibility — the sidebar content itself is always fully expanded.
 */
export function useSidebarFolded(): boolean {
  return useContext(SidebarFoldedContext);
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

interface SidebarRootProps {
  /**
   * Whether the sidebar is currently folded (desktop) or off-screen (mobile).
   */
  folded: boolean;
  /** Callback to update the fold state. Compatible with `useState` setters. */
  onFoldChange: Dispatch<SetStateAction<boolean>>;
  /**
   * Whether the sidebar supports folding on desktop.
   * When `false` (the default), the sidebar is always expanded on desktop and
   * the fold button is hidden. Mobile overlay behavior is always enabled
   * regardless of this prop.
   */
  foldable?: boolean;
  children: React.ReactNode;
}

function SidebarRoot({
  folded,
  onFoldChange,
  foldable = false,
  children,
}: SidebarRootProps) {
  const { isMobile, isMediumScreen } = useScreenSize();

  const close = useCallback(() => onFoldChange(true), [onFoldChange]);
  const toggle = useCallback(
    () => onFoldChange((prev) => !prev),
    [onFoldChange]
  );

  // On mobile the sidebar content is always visually expanded — the overlay
  // transform handles visibility. On desktop, only foldable sidebars honour
  // the fold state.
  const contentFolded = !isMobile && foldable ? folded : false;

  const inner = (
    <div className="flex flex-col min-h-0 h-full gap-3">{children}</div>
  );

  if (isMobile) {
    return (
      <SidebarFoldedContext.Provider value={false}>
        <div
          className={cn(
            "fixed inset-y-0 left-0 z-50 transition-transform duration-200",
            folded ? "-translate-x-full" : "translate-x-0"
          )}
        >
          <SidebarWrapper folded={false} onFoldClick={close}>
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
          onClick={close}
        />
      </SidebarFoldedContext.Provider>
    );
  }

  // Medium screens: the folded strip stays visible in the layout flow;
  // expanding overlays content instead of pushing it.
  if (isMediumScreen) {
    return (
      <SidebarFoldedContext.Provider value={folded}>
        {/* Spacer reserves the folded sidebar width in the flex layout */}
        <div className="shrink-0 w-[3.25rem]" />

        {/* Sidebar — fixed so it overlays content when expanded */}
        <div className="fixed inset-y-0 left-0 z-50">
          <SidebarWrapper folded={folded} onFoldClick={toggle}>
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
          onClick={close}
        />
      </SidebarFoldedContext.Provider>
    );
  }

  return (
    <SidebarFoldedContext.Provider value={contentFolded}>
      <SidebarWrapper
        folded={foldable ? folded : undefined}
        onFoldClick={foldable ? toggle : undefined}
      >
        {inner}
      </SidebarWrapper>
    </SidebarFoldedContext.Provider>
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
// Body — scrollable content area
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
  return (
    <OverflowDiv
      className={cn("gap-3 px-2", folded && "hidden")}
      scrollKey={scrollKey}
    >
      {children}
    </OverflowDiv>
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
