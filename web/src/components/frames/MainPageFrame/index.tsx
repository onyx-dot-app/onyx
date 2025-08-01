"use client";

import React from "react";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useChatContext } from "@/components/context/ChatContext";
import { useSidebar } from "@/components/context/SidebarProvider";
import { useSidebarShortcut } from "@/lib/browserUtilities";
import { NewChatIcon } from "@/components/icons/icons";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Link from "next/link";
import CollapsibleLogo from "../../logo/CollapsibleLogo";
import { Header } from "./Header";

interface MainPageFrameProps {
  children: React.ReactNode;
}

export default function MainPageFrame({ children }: MainPageFrameProps) {
  const { chatSessions, folders } = useChatContext();
  const {
    sidebarElementRef,
    sidebarPinned,
    sidebarVisible,
    toggleSidebarPinned,
  } = useSidebar();

  useSidebarShortcut(toggleSidebarPinned);

  return (
    <div className="flex relative overflow-x-hidden overscroll-contain flex-col w-full h-screen">
      <div className="flex flex-1 w-full">
        {/* Header framing
          Interestingly enough, the CollapsibleLogo is not a part of the Header.
          This is so that it can be a part of the seamless animation when opening/closing the sidebar.
        */}
        <div className="fixed top-[12px] left-[16px] z-30">
          <Link href="chat">
            <CollapsibleLogo />
          </Link>
        </div>
        <div className={`fixed top-0 w-full flex flex-1 justify-end z-10`}>
          <Header />
        </div>
      </div>

      {/* Sidebar framing */}
      <div
        ref={sidebarElementRef}
        className={`
          flex-none
          fixed
          left-0
          z-20
          bg-background-100
          h-screen
          transition-all
          bg-opacity-80
          duration-300
          ease-in-out
          ${
            sidebarVisible
              ? "opacity-100 w-[250px] translate-x-0"
              : "opacity-0 w-[200px] pointer-events-none -translate-x-10"
          }
        `}
      >
        <div className="w-full relative">
          <Sidebar
            existingChats={chatSessions}
            currentChatSession={null}
            folders={folders}
            sidebarVisible={sidebarVisible}
            sidebarPinned={sidebarPinned}
            toggleSidebarPinned={toggleSidebarPinned}
          />
        </div>
      </div>

      {/* Main content framing */}
      <main
        className={`flex flex-col h-full transition-all duration-300 ease-in-out ${sidebarPinned ? "pl-[250px]" : ""}`}
      >
        {children}
      </main>
    </div>
  );
}
