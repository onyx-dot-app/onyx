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

  // pinned
  sidebarPinned: boolean;
  setSidebarPinned: (pinned: boolean) => void;

  // pinned
  sidebarAreaMouseHover: boolean;
  setSidebarAreaMouseHover: (hover: boolean) => void;

  mobile?: boolean;
  isAnonymousUser?: boolean;
}

function useSidebarVisibility({
  sidebarElementRef,
  sidebarPinned,
  sidebarAreaMouseHover,
  setSidebarAreaMouseHover,
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
            setSidebarAreaMouseHover(true);
          }
        }

        if (
          currentXPosition > 100 &&
          sidebarAreaMouseHover &&
          !isWithinSidebar &&
          !sidebarPinned
        ) {
          setTimeout(() => {
            setSidebarAreaMouseHover(!(xPosition.current > sidebarRect.right));
          }, 200);
        } else if (currentXPosition < 100 && !sidebarAreaMouseHover) {
          if (!mobile) {
            setSidebarAreaMouseHover(true);
          }
        }
      }
    }

    function handleMouseLeave() {
      if (!mobile) {
        setSidebarAreaMouseHover(false);
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
  }, [sidebarAreaMouseHover, sidebarPinned, sidebarElementRef, mobile]);
}

// context

interface SidebarContextProps {
  sidebarElementRef: React.RefObject<HTMLDivElement>;

  // pinning
  sidebarPinned: boolean;
  toggleSidebarPinned: () => void;

  // visibility
  sidebarVisible: boolean;
  sidebarAreaMouseHover: boolean;
  setSidebarAreaMouseHover: (show: boolean) => void;
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
  const [sidebarAreaMouseHover, setSidebarAreaMouseHover] = useState(false);
  const sidebarElementRef = useRef<HTMLDivElement>(null);

  useSidebarVisibility({
    sidebarElementRef,
    sidebarPinned,
    setSidebarPinned,
    sidebarAreaMouseHover,
    setSidebarAreaMouseHover,
    mobile,
    isAnonymousUser,
  });

  const sidebarVisible = sidebarPinned || sidebarAreaMouseHover;

  return (
    <SidebarContext.Provider
      value={{
        sidebarVisible,
        sidebarElementRef,
        sidebarPinned,
        toggleSidebarPinned: () => setSidebarPinned((prev) => !prev),
        sidebarAreaMouseHover,
        setSidebarAreaMouseHover,
      }}
    >
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
