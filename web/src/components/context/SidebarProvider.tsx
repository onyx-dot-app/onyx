"use client";

import React, {
  createContext,
  useState,
  useContext,
  useCallback,
  useRef,
  useEffect,
  ReactNode,
} from "react";

// private hook

interface UseSidebarVisibilityProps {
  sidebarElementRef: React.RefObject<HTMLElement>;
  sidebarPinned: boolean;
  showSidebar: boolean;
  setShowSidebar: (show: boolean) => void;
  mobile?: boolean;
  isAnonymousUser?: boolean;
}

function useSidebarVisibility({
  sidebarElementRef,
  sidebarPinned,
  showSidebar,
  setShowSidebar,
  mobile,
  isAnonymousUser,
}: UseSidebarVisibilityProps) {
  const xPosition = useRef(0);

  useEffect(() => {
    function handleEvent(event: MouseEvent) {
      if (isAnonymousUser) {
        return;
      }
      const currentXPosition = event.clientX;
      xPosition.current = currentXPosition;

      const sidebarRect = sidebarElementRef.current?.getBoundingClientRect();

      if (sidebarRect && sidebarElementRef.current) {
        const isWithinSidebar =
          currentXPosition >= sidebarRect.left &&
          currentXPosition <= sidebarRect.right &&
          event.clientY >= sidebarRect.top &&
          event.clientY <= sidebarRect.bottom;

        const sidebarStyle = window.getComputedStyle(sidebarElementRef.current);
        const isVisible = sidebarStyle.opacity !== "0";
        if (isWithinSidebar && isVisible) {
          if (!mobile) {
            setShowSidebar(true);
          }
        }

        if (
          currentXPosition > 100 &&
          showSidebar &&
          !isWithinSidebar &&
          !sidebarPinned
        ) {
          setTimeout(() => {
            setShowSidebar(!(xPosition.current > sidebarRect.right));
          }, 200);
        } else if (currentXPosition < 100 && !showSidebar) {
          if (!mobile) {
            setShowSidebar(true);
          }
        }
      }
    }

    function handleMouseLeave() {
      if (!mobile) {
        setShowSidebar(false);
      }
    }

    if (!mobile) {
      document.addEventListener("mousemove", handleEvent);
      document.addEventListener("mouseleave", handleMouseLeave);
    }

    return function () {
      if (!mobile) {
        document.removeEventListener("mousemove", handleEvent);
        document.removeEventListener("mouseleave", handleMouseLeave);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showSidebar, sidebarPinned, sidebarElementRef, mobile]);
}

// context

interface SidebarContextProps {
  sidebarPinned: boolean;
  sidebarVisible: boolean;
  showSidebar: boolean;
  toggleSidebarPinned: () => void;
  setShowSidebar: (show: boolean) => void;
  sidebarElementRef: React.RefObject<HTMLDivElement>;
}

const SidebarContext = createContext<SidebarContextProps | undefined>(
  undefined
);

// public provider

interface SidebarProviderProps {
  children: ReactNode;
  mobile?: boolean;
  isAnonymousUser?: boolean;
}

export function SidebarProvider({
  children,
  mobile = false,
  isAnonymousUser = false,
}: SidebarProviderProps) {
  const [sidebarPinned, setSidebarPinned] = useState(true);
  const [showSidebar, setShowSidebar] = useState(false);
  const sidebarElementRef = useRef<HTMLDivElement>(null);

  const toggleSidebarPinned = useCallback(() => {
    setSidebarPinned((prev) => !prev);
  }, []);

  const setShowSidebarCallback = useCallback((show: boolean) => {
    setShowSidebar(show);
  }, []);

  useSidebarVisibility({
    sidebarElementRef,
    sidebarPinned,
    showSidebar,
    setShowSidebar: setShowSidebarCallback,
    mobile,
    isAnonymousUser,
  });

  const sidebarVisible = sidebarPinned || showSidebar;

  const contextValue: SidebarContextProps = {
    sidebarPinned,
    showSidebar,
    sidebarVisible,
    toggleSidebarPinned,
    setShowSidebar: setShowSidebarCallback,
    sidebarElementRef,
  };

  return (
    <SidebarContext.Provider value={contextValue}>
      {children}
    </SidebarContext.Provider>
  );
}

// public hook

export function useSidebar(): SidebarContextProps {
  const context = useContext(SidebarContext);
  if (context === undefined) {
    throw new Error("useSidebar must be used within a SidebarProvider");
  }
  return context;
}
