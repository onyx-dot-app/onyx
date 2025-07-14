import { useState, useRef, useCallback } from "react";
import Cookies from "js-cookie";
import { SIDEBAR_TOGGLED_COOKIE_NAME } from "@/components/resizable/constants";
import { useSidebarVisibility } from "@/components/chat/hooks";

export interface UseSidebarManagementProps {
  sidebarVisible: boolean;
  toggle: (toggled?: boolean) => void;
  user?: { is_anonymous_user?: boolean } | null;
  settings?: { isMobile?: boolean } | null;
}

export function useSidebarManagement({
  sidebarVisible,
  toggle,
  user,
  settings,
}: UseSidebarManagementProps) {
  // UI STATE: History sidebar visibility (shows chat history and navigation)
  const [showHistorySidebar, setShowHistorySidebar] = useState(false);

  // UI STATE: Document sidebar visibility (shows search results and selected documents)
  const [documentSidebarVisible, setDocumentSidebarVisible] = useState(false);

  // Used to maintain a "time out" for history sidebar so our existing refs can have time to process change
  // UI STATE: Sidebar untoggle animation state (prevents flickering during sidebar transitions)
  const [untoggled, setUntoggled] = useState(false);

  // UI REFS: Scroll and sidebar management
  const sidebarElementRef = useRef<HTMLDivElement>(null); // History sidebar container

  // UI FUNCTION: Explicitly close history sidebar with animation delay
  const explicitlyUntoggle = useCallback(() => {
    setShowHistorySidebar(false);

    setUntoggled(true);
    setTimeout(() => {
      setUntoggled(false);
    }, 200);
  }, []);

  // UI FUNCTION: Toggle history sidebar with cookie persistence
  const toggleSidebar = useCallback(() => {
    if (user?.is_anonymous_user) {
      return;
    }
    Cookies.set(
      SIDEBAR_TOGGLED_COOKIE_NAME,
      String(!sidebarVisible).toLocaleLowerCase()
    ),
      {
        path: "/",
      };

    toggle();
  }, [user?.is_anonymous_user, sidebarVisible, toggle]);

  // UI FUNCTION: Remove sidebar toggle state (close sidebar)
  const removeToggle = useCallback(() => {
    setShowHistorySidebar(false);
    toggle(false);
  }, [toggle]);

  // UI FUNCTION: Toggle document sidebar visibility
  const toggleDocumentSidebar = useCallback(() => {
    if (!documentSidebarVisible) {
      setDocumentSidebarVisible(true);
    } else {
      setDocumentSidebarVisible(false);
    }
  }, [documentSidebarVisible]);

  useSidebarVisibility({
    sidebarVisible,
    sidebarElementRef,
    showDocSidebar: showHistorySidebar,
    setShowDocSidebar: setShowHistorySidebar,
    setToggled: removeToggle,
    mobile: settings?.isMobile,
    isAnonymousUser: user?.is_anonymous_user,
  });

  return {
    showHistorySidebar,
    setShowHistorySidebar,
    documentSidebarVisible,
    setDocumentSidebarVisible,
    untoggled,
    sidebarElementRef,
    explicitlyUntoggle,
    toggleSidebar,
    removeToggle,
    toggleDocumentSidebar,
  };
}
