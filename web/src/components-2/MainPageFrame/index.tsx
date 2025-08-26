"use client";

import React from "react";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useChatContext } from "@/components/context/ChatContext";
import { useSidebar } from "@/components/context/SidebarProvider";
import { useSidebarShortcut } from "@/lib/browserUtilities";
import Link from "next/link";
import { Header } from "@/components-2/Header";
import CollapsibleLogo from "@/components/logo/CollapsibleLogo";

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
        {/* Logo framing
          Interestingly enough, the CollapsibleLogo is not a part of the Header.
          This is so that it can be a part of the seamless animation when opening/closing the sidebar.
        */}
        <div className="fixed top-[12px] left-[16px] z-30">
          <Link href="chat">
            <CollapsibleLogo />
          </Link>
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

      <main className="flex flex-col h-full">
        {/* Header framing */}
        <div
          className={`flex justify-end z-10 transition-all duration-300 ease-in-out ${sidebarVisible ? "pl-[250px]" : ""}`}
        >
          <Header />
        </div>
        {/* Main content framing */}
        <div
          className={`overflow-hidden transition-all duration-300 ease-in-out flex flex-1 justify-center ${sidebarPinned ? "pl-[250px]" : ""}`}
        >
          {children}
        </div>
      </main>
    </div>
  );
}
