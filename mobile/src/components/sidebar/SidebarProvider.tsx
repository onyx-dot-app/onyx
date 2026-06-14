import {
  createContext,
  useContext,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";

// ---------------------------------------------------------------------------
// Sidebar state. `folded` is the single source of truth: on a phone the sidebar
// is an overlay, so `folded === true` means "closed / off-screen" and
// `folded === false` means "open". Default closed; opened from a trigger.
//
// `setFolded` is React's own `useState` setter, so it already accepts either a
// value (`setFolded(false)`) or an updater (`setFolded((prev) => !prev)` for a
// toggle) — no wrapper needed.
// ---------------------------------------------------------------------------

export interface SidebarStateContextType {
  folded: boolean;
  setFolded: Dispatch<SetStateAction<boolean>>;
}

const SidebarStateContext = createContext<SidebarStateContextType | undefined>(
  undefined,
);

export interface SidebarProviderProps {
  /** Initial fold state. Defaults to `true` (closed) on mobile. */
  defaultFolded?: boolean;
  children: ReactNode;
}

export function SidebarProvider({
  defaultFolded = true,
  children,
}: SidebarProviderProps) {
  const [folded, setFolded] = useState(defaultFolded);

  return (
    <SidebarStateContext.Provider value={{ folded, setFolded }}>
      {children}
    </SidebarStateContext.Provider>
  );
}

export function useSidebar(): SidebarStateContextType {
  const context = useContext(SidebarStateContext);
  if (context === undefined) {
    throw new Error("useSidebar must be used within a SidebarProvider");
  }
  return context;
}
