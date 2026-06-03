"use client";

import "@opal/layouts/root/styles.css";
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
  return <div className="opal-root-layout">{children}</div>;
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
  const foldedAttr = folded ? "true" : "false";

  if (isMobile) {
    return (
      <RootLayoutFoldedContext.Provider value={false}>
        <div
          className="opal-root-layout__sidebar-overlay"
          data-variant="mobile"
          data-folded={foldedAttr}
        >
          {children}
        </div>

        {/* Closes the sidebar when anything outside it is tapped */}
        <div
          className="opal-root-layout__backdrop"
          data-variant="mobile"
          data-folded={foldedAttr}
          onClick={onFoldToggle}
        />
      </RootLayoutFoldedContext.Provider>
    );
  }

  if (isMediumScreen) {
    return (
      <RootLayoutFoldedContext.Provider value={folded}>
        {/* Spacer reserves the folded-sidebar width in the flex layout */}
        <div className="opal-root-layout__sidebar-spacer" />

        {/* Fixed so it overlays content when expanded */}
        <div
          className="opal-root-layout__sidebar-overlay"
          data-variant="medium"
        >
          {children}
        </div>

        {/* Blur-only backdrop when expanded */}
        <div
          className="opal-root-layout__backdrop"
          data-variant="medium"
          data-folded={foldedAttr}
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
// App — fills remaining flex space; use as direct child of Root
// ---------------------------------------------------------------------------

type RootLayoutAppProps = React.HTMLAttributes<HTMLDivElement>;

function RootLayoutApp({ children, className, ...props }: RootLayoutAppProps) {
  return (
    <div className={cn("opal-root-layout__app", className)} {...props}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MainContent — scrollable content slot inside App
// ---------------------------------------------------------------------------

type RootLayoutMainContentProps = React.HTMLAttributes<HTMLDivElement>;

function RootLayoutMainContent({
  children,
  className,
  ...props
}: RootLayoutMainContentProps) {
  return (
    <div className={cn("opal-root-layout__main", className)} {...props}>
      {children}
    </div>
  );
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
    <div className={cn("opal-root-layout__panel", className)}>{children}</div>
  );
}

function RootLayoutRightPanel({ children, className }: RootLayoutPanelProps) {
  return (
    <div className={cn("opal-root-layout__panel", className)}>{children}</div>
  );
}

// ---------------------------------------------------------------------------
// Header — pinned top bar inside MainContent
// ---------------------------------------------------------------------------

interface RootLayoutHeaderProps {
  children: ReactNode;
}

function RootLayoutHeader({ children }: RootLayoutHeaderProps) {
  return <div className="opal-root-layout__header">{children}</div>;
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
    <div
      className="opal-root-layout__footer"
      data-extra-padding={extraPadding || undefined}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  RootLayoutRoot as Root,
  RootLayoutSidebar as Sidebar,
  RootLayoutApp as App,
  RootLayoutMainContent as MainContent,
  RootLayoutLeftPanel as LeftPanel,
  RootLayoutRightPanel as RightPanel,
  RootLayoutHeader as Header,
  RootLayoutFooter as Footer,
};
