"use client";

import { createContext, useContext, type ReactNode } from "react";
import { cn } from "@opal/utils";
import useScreenSize from "@opal/hooks/useScreenSize";

// ---------------------------------------------------------------------------
// Folded context — readable by sidebar body content via useSidebarFolded()
// ---------------------------------------------------------------------------

export const RootLayoutFoldedContext = createContext(false);

/**
 * Returns the effective sidebar fold state for content rendering.
 * On mobile this is always `false` — the sidebar content is always fully
 * expanded; the overlay transform handles visibility instead.
 */
export function useSidebarFolded(): boolean {
  return useContext(RootLayoutFoldedContext);
}

// ---------------------------------------------------------------------------
// Root — flex container
// ---------------------------------------------------------------------------

interface RootLayoutRootProps {
  children: ReactNode;
}

function RootLayoutRoot({ children }: RootLayoutRootProps) {
  return <div className="flex flex-row w-full h-full">{children}</div>;
}

// ---------------------------------------------------------------------------
// Sidebar — handles mobile / medium / desktop positioning
// ---------------------------------------------------------------------------

interface RootLayoutSidebarProps {
  /**
   * Whether the sidebar is currently folded (collapsed on desktop, hidden on
   * mobile). Controlled by the consumer — typically read from a persistent
   * state provider such as `SidebarStateProvider`.
   */
  folded: boolean;
  /** Called when the sidebar fold state should toggle. */
  onFoldToggle: () => void;
  children: ReactNode;
}

function RootLayoutSidebar({
  folded,
  onFoldToggle,
  children,
}: RootLayoutSidebarProps) {
  const { isMobile, isMediumScreen } = useScreenSize();

  if (isMobile) {
    return (
      <RootLayoutFoldedContext.Provider value={false}>
        <div
          className={cn(
            "fixed inset-y-0 left-0 z-50 transition-transform duration-200",
            folded ? "-translate-x-full" : "translate-x-0"
          )}
        >
          {children}
        </div>

        {/* Closes the sidebar when anything outside it is tapped */}
        <div
          className={cn(
            "fixed inset-0 z-40 bg-mask-03 backdrop-blur-03 transition-opacity duration-200",
            folded
              ? "opacity-0 pointer-events-none"
              : "opacity-100 pointer-events-auto"
          )}
          onClick={onFoldToggle}
        />
      </RootLayoutFoldedContext.Provider>
    );
  }

  if (isMediumScreen) {
    return (
      <RootLayoutFoldedContext.Provider value={folded}>
        {/* Spacer reserves the folded-sidebar width in the flex layout */}
        <div className="shrink-0 w-(--sidebar-width-folded)" />

        {/* Fixed so it overlays content when expanded */}
        <div className="fixed inset-y-0 left-0 z-50">{children}</div>

        {/* Blur-only backdrop when expanded */}
        <div
          className={cn(
            "fixed inset-0 z-40 backdrop-blur-03 transition-opacity duration-200",
            folded
              ? "opacity-0 pointer-events-none"
              : "opacity-100 pointer-events-auto"
          )}
          onClick={onFoldToggle}
        />
      </RootLayoutFoldedContext.Provider>
    );
  }

  // Desktop — normal flex-row flow
  return (
    <RootLayoutFoldedContext.Provider value={folded}>
      {children}
    </RootLayoutFoldedContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// MainContent — fills remaining flex space
// ---------------------------------------------------------------------------

function RootLayoutMainContent({ children }: { children: ReactNode }) {
  return <div className="flex-1 overflow-auto h-full w-full">{children}</div>;
}

// ---------------------------------------------------------------------------
// Left / Right panels — permanent columns that push content
// ---------------------------------------------------------------------------

interface RootLayoutPanelProps {
  children: ReactNode;
  className?: string;
}

function RootLayoutLeftPanel({ children, className }: RootLayoutPanelProps) {
  return (
    <div className={cn("shrink-0 overflow-auto h-full", className)}>
      {children}
    </div>
  );
}

function RootLayoutRightPanel({ children, className }: RootLayoutPanelProps) {
  return (
    <div className={cn("shrink-0 overflow-auto h-full", className)}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header — pinned top bar inside MainContent
// ---------------------------------------------------------------------------

interface RootLayoutHeaderProps {
  children: ReactNode;
}

function RootLayoutHeader({ children }: RootLayoutHeaderProps) {
  return <div className="shrink-0">{children}</div>;
}

// ---------------------------------------------------------------------------
// Footer — pinned bottom bar inside MainContent
// ---------------------------------------------------------------------------

interface RootLayoutFooterProps {
  children: ReactNode;
  /**
   * Adds top padding to give shadow breathing room above the input bar.
   * Used when an animated spacer is not present (e.g. outside active chat).
   */
  extraPadding?: boolean;
}

function RootLayoutFooter({
  children,
  extraPadding = false,
}: RootLayoutFooterProps) {
  return (
    <div className={cn("shrink-0", extraPadding && "pt-3.5")}>{children}</div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  RootLayoutRoot as Root,
  RootLayoutSidebar as Sidebar,
  RootLayoutMainContent as MainContent,
  RootLayoutLeftPanel as LeftPanel,
  RootLayoutRightPanel as RightPanel,
  RootLayoutHeader as Header,
  RootLayoutFooter as Footer,
};
