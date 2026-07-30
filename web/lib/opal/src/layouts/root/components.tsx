"use client";

import "@opal/layouts/root/styles.css";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Sidebar state — raw fold state + setter, owned here as the single source
// of truth. SidebarRoot (in sidebar/components.tsx) derives contentFolded
// and provides RootLayoutFoldedContext from this.
// ---------------------------------------------------------------------------

export interface SidebarStateContextType {
  folded: boolean;
  setFolded: Dispatch<SetStateAction<boolean>>;
}

export const SidebarStateContext = createContext<
  SidebarStateContextType | undefined
>(undefined);

export interface SidebarStateProviderProps {
  /** Initial fold state, typically read from a persisted cookie by the app. */
  defaultFolded?: boolean;
  /** Called whenever the fold state changes, e.g. to persist to a cookie. */
  onFoldedChange?: (folded: boolean) => void;
  children: ReactNode;
}

export function SidebarStateProvider({
  defaultFolded = false,
  onFoldedChange,
  children,
}: SidebarStateProviderProps) {
  const [folded, setFoldedInternal] = useState(defaultFolded);

  const onFoldedChangeRef = useRef(onFoldedChange);
  onFoldedChangeRef.current = onFoldedChange;

  const setFolded: Dispatch<SetStateAction<boolean>> = useCallback((value) => {
    setFoldedInternal((prev) =>
      typeof value === "function" ? value(prev) : value
    );
  }, []);

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
      const target = event.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      ) {
        return;
      }
      const isMac = navigator.userAgent.toLowerCase().includes("mac");
      const isModifierPressed = isMac ? event.metaKey : event.ctrlKey;
      if (!isModifierPressed || event.key !== "e") return;
      event.preventDefault();
      setFolded((prev) => !prev);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [setFolded]);

  return (
    <SidebarStateContext.Provider value={{ folded, setFolded }}>
      {children}
    </SidebarStateContext.Provider>
  );
}

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
// Root — flex container
// ---------------------------------------------------------------------------

interface RootLayoutRootProps {
  children: ReactNode;
}

function RootLayoutRoot({ children }: RootLayoutRootProps) {
  return <div className="opal-root-layout">{children}</div>;
}

// ---------------------------------------------------------------------------
// App — fills remaining flex space; use as direct child of Root
// ---------------------------------------------------------------------------

type RootLayoutAppProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>>;

function RootLayoutApp({ children, ...props }: RootLayoutAppProps) {
  return (
    <div className="opal-root-layout__app" {...props}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MainContent — scrollable content slot inside App
// ---------------------------------------------------------------------------

type RootLayoutMainContentProps = WithoutStyles<
  React.HTMLAttributes<HTMLDivElement>
>;

function RootLayoutMainContent({
  children,
  ...props
}: RootLayoutMainContentProps) {
  return (
    <div className="opal-root-layout__main" {...props}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Left / Right panels — permanent columns that push content
// ---------------------------------------------------------------------------

interface RootLayoutPanelProps {
  children: ReactNode;
}

function RootLayoutPanel({ children }: RootLayoutPanelProps) {
  return <div className="opal-root-layout__panel">{children}</div>;
}

function RootLayoutLeftPanel(props: RootLayoutPanelProps) {
  return <RootLayoutPanel {...props} />;
}

// When provided, RightPanel hoists itself into this slot (set by the host
// layout, e.g. AppChrome) instead of rendering in place. This lets it sit as
// a flex sibling to the Header/Content/Footer column and push the whole column
// in, regardless of where in the tree RightPanel is actually rendered.
export type RightPanelSlotSetter = Dispatch<SetStateAction<ReactNode>>;
export const RootLayoutRightPanelSlotContext =
  createContext<RightPanelSlotSetter | null>(null);

function RootLayoutRightPanel({ children }: RootLayoutPanelProps) {
  const setSlot = useContext(RootLayoutRightPanelSlotContext);

  useLayoutEffect(() => {
    if (!setSlot) return;
    const content = <RootLayoutPanel>{children}</RootLayoutPanel>;
    setSlot(content);
    return () => setSlot((prev) => (prev === content ? null : prev));
  }, [setSlot, children]);

  if (setSlot) return null;
  return <RootLayoutPanel>{children}</RootLayoutPanel>;
}

// ---------------------------------------------------------------------------
// Header — pinned top bar inside MainContent
// ---------------------------------------------------------------------------

interface RootLayoutHeaderProps {
  children: ReactNode;
}

function RootLayoutHeader({ children }: RootLayoutHeaderProps) {
  return <header className="opal-root-layout__header">{children}</header>;
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
    <footer
      className="opal-root-layout__footer"
      data-extra-padding={extraPadding || undefined}
    >
      {children}
    </footer>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  RootLayoutRoot as Root,
  RootLayoutApp as App,
  RootLayoutMainContent as MainContent,
  RootLayoutLeftPanel as LeftPanel,
  RootLayoutRightPanel as RightPanel,
  RootLayoutHeader as Header,
  RootLayoutFooter as Footer,
};
