"use client";

import { useCallback, useRef } from "react";
import { RootLayout } from "@opal/layouts";
import { INTERACTIVE_SELECTOR } from "@/lib/utils";
import AppHeader from "@/sections/app-chrome/AppHeader";
import AppFooter from "@/sections/app-chrome/AppFooter";

interface AppChromeProps {
  children: React.ReactNode;
}

export default function AppChrome({ children }: AppChromeProps) {
  const inputWasFocused = useRef(false);

  // Track whether the chat input was focused before a mousedown, so we can
  // restore focus on mouseup if no text was selected. This preserves
  // click-drag text selection while keeping the input focused on plain clicks.
  const handleMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const activeEl = document.activeElement;
      const isFocused =
        activeEl instanceof HTMLElement &&
        activeEl.id === "onyx-chat-input-textbox";
      const target = event.target;
      const isInteractive =
        target instanceof HTMLElement && !!target.closest(INTERACTIVE_SELECTOR);
      inputWasFocused.current = isFocused && !isInteractive;
    },
    []
  );

  const handleMouseUp = useCallback(() => {
    if (!inputWasFocused.current) return;
    inputWasFocused.current = false;
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed) return;
    const textarea = document.getElementById("onyx-chat-input-textbox");
    if (textarea && document.activeElement !== textarea) {
      textarea.focus();
    }
  }, []);

  return (
    <RootLayout.App
      data-main-container
      className="@container"
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
    >
      <RootLayout.Header>
        <AppHeader />
      </RootLayout.Header>
      <RootLayout.MainContent>{children}</RootLayout.MainContent>
      <RootLayout.Footer>
        <AppFooter />
      </RootLayout.Footer>
    </RootLayout.App>
  );
}
