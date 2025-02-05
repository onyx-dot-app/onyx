"use client";

import { MacIcon, WindowsIcon } from "@/components/icons/icons";
import { useState, useEffect } from "react";

export enum OperatingSystem {
  Windows = "Windows",
  Mac = "Mac",
  Other = "Other",
}

export const useOperatingSystem = (): OperatingSystem => {
  const [os, setOS] = useState<OperatingSystem>(OperatingSystem.Other);

  useEffect(() => {
    const userAgent = window.navigator.userAgent.toLowerCase();
    if (userAgent.includes("win")) {
      setOS(OperatingSystem.Windows);
    } else if (userAgent.includes("mac")) {
      setOS(OperatingSystem.Mac);
    }
  }, []);

  return os;
};

// Use this to handle the sidebar shortcut for the chat page
// The shortcut is Ctrl+E on Windows/Linux and Cmd+E on Mac
// This hook handles the keyboard event and toggles the sidebar
export const useSidebarShortcut = (router: any, toggleSidebar: () => void) => {
  const os = useOperatingSystem();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const isMac = os === OperatingSystem.Mac;
      const modifierKey = isMac ? event.metaKey : event.ctrlKey;

      if (modifierKey && event.key.toLowerCase() === "e") {
        event.preventDefault();
        toggleSidebar();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [router, toggleSidebar, os]);
};

const KeyboardSymbol = () => {
  const os = useOperatingSystem();

  if (os === OperatingSystem.Windows) {
    return <WindowsIcon size={12} />;
  } else {
    return <MacIcon size={12} />;
  }
};

export default KeyboardSymbol;
