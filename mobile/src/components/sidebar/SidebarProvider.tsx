import {
  createContext,
  useContext,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";

// `folded === true` means closed/off-screen (the overlay's source of truth).
export interface SidebarStateContextType {
  folded: boolean;
  setFolded: Dispatch<SetStateAction<boolean>>;
}

const SidebarStateContext = createContext<SidebarStateContextType | undefined>(
  undefined,
);

export interface SidebarProviderProps {
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
